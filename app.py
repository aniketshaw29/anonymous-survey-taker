"""
anonymous-survey-taker — application entry point.

A small Flask app for hosting anonymous surveys.

Core ideas
----------
* Anyone can CREATE a survey (no account, no login).
* The creator receives two links at creation time:
    1. A PUBLIC link  -> anyone can fill the survey in anonymously.
    2. A SECRET link  -> lets the creator view results / edit / close / delete.
* The app deliberately stores NO identifying information about respondents:
  no IP addresses, no cookies, no user agents, no timestamps tied to a person.
  A response row only records *what* was answered and *when the survey* got
  the answer — nothing about *who* answered.

Database
--------
SQLite (file: ``survey.db``) via the standard-library ``sqlite3`` module.
The schema lives in ``schema.sql`` and is applied on startup.

Run locally
----------
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python app.py
    # -> http://127.0.0.1:5000
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Absolute path of the folder this file lives in.
BASE_DIR = Path(__file__).resolve().parent

# Path to the SQLite database file. Created on first run.
DATABASE = BASE_DIR / "survey.db"

# Path to the SQL schema that gets executed on every startup.
# ``IF NOT EXISTS`` clauses make re-running it harmless.
SCHEMA = BASE_DIR / "schema.sql"

# Question types the builder supports. Kept here so validation in one place.
QUESTION_TYPES = ("choice", "text", "rating")

# Maximum number of options allowed for a single multiple-choice question.
MAX_OPTIONS = 10

app = Flask(__name__)

# Flask needs a secret key to sign session cookies (used by ``flash()``).
# A random per-process key means flash messages don't survive a restart,
# which is fine for this app. Set an env var in production for stability.
app.config["SECRET_KEY"] = secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


class Row(sqlite3.Row):
    """A sqlite3.Row that ALSO supports attribute access.

    The ORM-free sqlite3 module only allows ``row["title"]``, but Jinja
    templates read more naturally as ``survey.title``. This subclass
    bridges the two styles: indexing (used in Python code) and dotted
    access (used in templates) both work on the same row objects.
    """

    def __getattr__(self, name: str):
        try:
            return self[name]
        except IndexError as exc:
            raise AttributeError(name) from exc


def get_db() -> sqlite3.Connection:
    """Return the per-request SQLite connection.

    Flask's ``g`` object is scoped to a single request, so every helper in
    this module shares exactly one connection per request. Connections are
    opened lazily and closed automatically in ``close_db``.
    """
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        # ``row_factory = Row`` lets us access columns by name
        # (e.g. ``row["title"]`` or ``row.title``).
        g.db.row_factory = Row
        # Enforce FOREIGN KEY constraints (SQLite disables them by default).
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception: BaseException | None) -> None:
    """Close the request-scoped connection when the request finishes."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Create tables if they don't exist yet (idempotent)."""
    db = sqlite3.connect(DATABASE)
    try:
        db.executescript(SCHEMA.read_text())
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def new_id() -> str:
    """Generate a short, URL-safe public survey id (e.g. ``k3FpQ2xW``).

    8 bytes -> 12 base64url chars without padding. Collision risk is
    negligible at this scale, and the id is checked against the DB anyway.
    """
    return secrets.token_urlsafe(8)


def new_secret() -> str:
    """Generate the creator's secret key (longer & harder to guess)."""
    return secrets.token_urlsafe(24)


def get_survey_or_404(survey_id: str) -> sqlite3.Row:
    """Fetch a survey row or abort with a 404.

    ``abort(404)`` raises an exception Flask turns into its 404 page,
    so callers can simply ``return get_survey_or_404(...)``.
    """
    row = get_db().execute(
        "SELECT * FROM surveys WHERE id = ?", (survey_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


def check_secret(survey: sqlite3.Row, supplied: str | None) -> None:
    """Abort with 403 unless ``supplied`` matches the survey's secret.

    Uses ``secrets.compare_digest`` (constant-time comparison) so an
    attacker can't guess the secret faster by measuring response times.
    """
    if not supplied or not secrets.compare_digest(survey["secret"], supplied):
        abort(403)


def load_questions(survey_id: str) -> list[sqlite3.Row]:
    """Return all questions for a survey, ordered by position."""
    return (
        get_db()
        .execute(
            "SELECT * FROM questions WHERE survey_id = ? ORDER BY position",
            (survey_id,),
        )
        .fetchall()
    )


def parse_options(raw: str) -> list[str]:
    """Decode the JSON ``options`` column into a list of strings.

    Corrupt data (shouldn't happen) degrades to an empty list rather
    than crashing the results page.
    """
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return value if isinstance(value, list) else []


# Expose parse_options to Jinja templates as the `| from_json` filter.
# Used by take.html (render choice options) and edit.html (pre-fill them).
app.jinja_env.filters["from_json"] = parse_options


def count_responses(survey_id: str) -> int:
    """How many anonymous submissions this survey has received."""
    row = get_db().execute(
        "SELECT COUNT(*) AS n FROM responses WHERE survey_id = ?",
        (survey_id,),
    ).fetchone()
    return int(row["n"])


# ---------------------------------------------------------------------------
# Routes — public pages
# ---------------------------------------------------------------------------


@app.route("/")
def index() -> str:
    """Landing page: the survey-builder form.

    Also renders the (empty) list of links the creator already opened in
    this browser session — see ``create_survey`` for how those get flashed.
    """
    return render_template("index.html", question_types=QUESTION_TYPES)


@app.post("/surveys")
def create_survey() -> str:
    """Handle the builder form POST and create a new survey.

    Flow:
      1. Validate title + at least one question.
      2. Insert the survey row (with a fresh secret).
      3. Insert each question row, JSON-encoding the choice options.
      4. Show a confirmation page containing both links.
    """
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    if not title:
        flash("A survey needs a title.")
        return redirect(url_for("index"))

    # The builder submits questions as parallel lists:
    #   q_type[0], q_type[1], ...   q_prompt[0], ...
    #   q_required[0], ...
    # and, for choice questions, ``q_options_<index>`` (newline separated).
    types = request.form.getlist("q_type")
    prompts = request.form.getlist("q_prompt")
    required_flags = request.form.getlist("q_required")

    # Only keep entries where the author actually typed a prompt.
    questions: list[dict] = []
    for i, prompt in enumerate(prompts):
        prompt = prompt.strip()
        if not prompt:
            continue
        q_type = types[i] if i < len(types) else "text"
        if q_type not in QUESTION_TYPES:
            q_type = "text"
        required = "1" if str(i) in required_flags else "0"

        options: list[str] = []
        if q_type == "choice":
            raw = request.form.get(f"q_options_{i}", "")
            # Split on newlines, drop blanks, de-duplicate while preserving order.
            seen: set[str] = set()
            for line in raw.splitlines():
                line = line.strip()
                if line and line not in seen:
                    seen.add(line)
                    options.append(line)
            if len(options) < 2:
                flash("Multiple-choice questions need at least 2 options.")
                return redirect(url_for("index"))

        questions.append(
            {
                "type": q_type,
                "prompt": prompt,
                "required": required,
                "options": options,
            }
        )

    if not questions:
        flash("Add at least one question.")
        return redirect(url_for("index"))

    db = get_db()
    survey_id = new_id()
    secret = new_secret()

    db.execute(
        "INSERT INTO surveys (id, secret, title, description) VALUES (?, ?, ?, ?)",
        (survey_id, secret, title, description),
    )
    for position, q in enumerate(questions):
        db.execute(
            """
            INSERT INTO questions (survey_id, position, type, prompt, options, required)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                survey_id,
                position,
                q["type"],
                q["prompt"],
                json.dumps(q["options"]),
                q["required"],
            ),
        )
    db.commit()

    return render_template(
        "created.html",
        survey_id=survey_id,
        secret=secret,
        title=title,
    )


@app.get("/s/<survey_id>")
def take_survey(survey_id: str) -> str:
    """Render the public, anonymous fill-in page.

    Anyone holding this URL can respond — that's the point. The page
    includes a short privacy note so respondents know nothing identifying
    is collected.
    """
    survey = get_survey_or_404(survey_id)
    if survey["closed"]:
        return render_template("closed.html", survey=survey)
    return render_template(
        "take.html", survey=survey, questions=load_questions(survey_id)
    )


@app.post("/s/<survey_id>")
def submit_response(survey_id: str) -> str:
    """Store one anonymous response.

    Deliberately NOT recorded here (anonymity guarantees):
      * client IP address
      * cookies / session ids
      * user-agent header
      * precise timestamp (we keep only a coarse date for the creator's
        own bookkeeping, and no per-answer identity links)

    Each response gets an auto-increment id, but it is never shown to
    respondents and carries no personal data — it just groups answers.
    """
    survey = get_survey_or_404(survey_id)
    if survey["closed"]:
        abort(403)

    questions = load_questions(survey_id)
    db = get_db()

    # First pass: validate everything BEFORE writing, so a rejected
    # submission never leaves a half-inserted response behind.
    answers: list[tuple[int, str]] = []
    for q in questions:
        key = f"q{q['id']}"
        value = request.form.get(key, "").strip()
        q_required = bool(q["required"])

        if q["type"] == "choice":
            options = parse_options(q["options"])
            if value not in options:
                # Empty optional choice answers are fine; bogus ones aren't.
                if value:
                    abort(400)
                if q_required:
                    flash(f"Please answer: {q['prompt']}")
                    return redirect(url_for("take_survey", survey_id=survey_id))
                continue
        elif q["type"] == "rating":
            if value:
                # Rating widget submits "1".."5"; reject anything else.
                if value not in {"1", "2", "3", "4", "5"}:
                    abort(400)
            elif q_required:
                flash(f"Please rate: {q['prompt']}")
                return redirect(url_for("take_survey", survey_id=survey_id))
            else:
                continue
        else:  # text
            if len(value) > 5000:
                abort(400)  # cap free-text size
            if not value and q_required:
                flash(f"Please answer: {q['prompt']}")
                return redirect(url_for("take_survey", survey_id=survey_id))
            else:
                if not value:
                    continue

        answers.append((q["id"], value))

    # Second pass: single transaction so the response and its answers
    # are either all written or none at all.
    cursor = db.execute(
        "INSERT INTO responses (survey_id) VALUES (?)", (survey_id,)
    )
    response_id = cursor.lastrowid
    db.executemany(
        "INSERT INTO answers (response_id, question_id, value) VALUES (?, ?, ?)",
        [(response_id, qid, val) for qid, val in answers],
    )
    db.commit()

    return render_template("thanks.html", survey=survey)


# ---------------------------------------------------------------------------
# Routes — creator-only pages (guarded by the secret key)
# ---------------------------------------------------------------------------


@app.get("/s/<survey_id>/results")
def results(survey_id: str) -> str:
    """Dashboard with aggregate results, protected by ``?key=``.

    Aggregation happens server-side:
      * choice  -> count of each option + a bar width percentage
      * rating  -> average + per-star histogram
      * text    -> the raw (anonymous) free-text answers
    """
    survey = get_survey_or_404(survey_id)
    check_secret(survey, request.args.get("key"))

    db = get_db()
    questions = load_questions(survey_id)
    total = count_responses(survey_id)

    # Pre-fetch every answer once, then group in Python. Fine at this scale.
    rows = db.execute(
        """
        SELECT question_id, value, COUNT(*) AS n
        FROM answers
        WHERE response_id IN (SELECT id FROM responses WHERE survey_id = ?)
        GROUP BY question_id, value
        """,
        (survey_id,),
    ).fetchall()

    grouped: dict[int, dict[str, int]] = {}
    for row in rows:
        grouped.setdefault(row["question_id"], {})[row["value"]] = row["n"]

    stats = []
    for q in questions:
        counts = grouped.get(q["id"], {})
        entry = {"question": q, "total_answers": sum(counts.values())}

        if q["type"] == "choice":
            options = parse_options(q["options"])
            # Keep the author's option order; missing options show as 0.
            bars = []
            for opt in options:
                n = counts.get(opt, 0)
                pct = round(100 * n / total) if total else 0
                bars.append({"label": opt, "count": n, "pct": pct})
            entry["bars"] = bars
            entry["top"] = max(bars, key=lambda b: b["count"])["label"] if total else None

        elif q["type"] == "rating":
            # Histogram of star values 1..5 + weighted average.
            # Pre-compute bar percentages here because Jinja templates
            # have no ``round()`` *function* (only a | round filter).
            histogram = {str(i): counts.get(str(i), 0) for i in range(1, 6)}
            answered = sum(histogram.values())
            weighted = sum(int(k) * v for k, v in histogram.items())
            entry["histogram"] = histogram
            entry["answered"] = answered
            entry["average"] = round(weighted / answered, 2) if answered else None
            entry["hist_rows"] = [
                {
                    "star": star,
                    "count": n,
                    "pct": round(100 * n / answered) if answered else 0,
                }
                for star, n in histogram.items()
            ]

        else:  # text — show the answers themselves (they contain no PII)
            texts = sorted(
                (
                    v
                    for v, n in counts.items()
                    for _ in range(n)  # expand counts back into instances
                ),
                key=str.lower,
            )
            entry["texts"] = texts

        stats.append(entry)

    return render_template(
        "results.html", survey=survey, stats=stats, total=total, key=survey["secret"]
    )


@app.route("/s/<survey_id>/edit", methods=["GET", "POST"])
def edit_survey(survey_id: str) -> str:
    """Edit a survey's title/description and its questions (secret required).

    The simplest safe strategy: delete all existing questions and
    re-insert the submitted ones. Answers reference question ids, so we
    only do this while the survey has no responses OR we keep questions
    whose prompts are unchanged.

    To keep things predictable we take the straightforward route:
    question edits ARE allowed after responses arrive, but deleting a
    question also deletes its answers (ON DELETE CASCADE). The UI warns
    the creator about that.
    """
    survey = get_survey_or_404(survey_id)
    # Accept the secret from query string or form field so GET links
    # (with ?key=) keep working across the POST round-trip.
    supplied = request.values.get("key")
    check_secret(survey, supplied)

    db = get_db()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("A survey needs a title.")
            return redirect(url_for("edit_survey", survey_id=survey_id, key=survey["secret"]))

        types = request.form.getlist("q_type")
        prompts = request.form.getlist("q_prompt")
        required_flags = request.form.getlist("q_required")

        questions: list[dict] = []
        for i, prompt in enumerate(prompts):
            prompt = prompt.strip()
            if not prompt:
                continue
            q_type = types[i] if i < len(types) else "text"
            if q_type not in QUESTION_TYPES:
                q_type = "text"
            options: list[str] = []
            if q_type == "choice":
                raw = request.form.get(f"q_options_{i}", "")
                seen: set[str] = set()
                for line in raw.splitlines():
                    line = line.strip()
                    if line and line not in seen:
                        seen.add(line)
                        options.append(line)
                if len(options) < 2:
                    flash("Multiple-choice questions need at least 2 options.")
                    return redirect(url_for("edit_survey", survey_id=survey_id, key=survey["secret"]))
            questions.append(
                {
                    "type": q_type,
                    "prompt": prompt,
                    "required": "1" if str(i) in required_flags else "0",
                    "options": options,
                }
            )

        if not questions:
            flash("A survey needs at least one question.")
            return redirect(url_for("edit_survey", survey_id=survey_id, key=survey["secret"]))

        db.execute("UPDATE surveys SET title = ?, description = ? WHERE id = ?",
                   (title, description, survey_id))
        # Cascade wipes old questions AND their answers — intentional:
        # editing the question set invalidates old answers to removed items.
        db.execute("DELETE FROM questions WHERE survey_id = ?", (survey_id,))
        for position, q in enumerate(questions):
            db.execute(
                """
                INSERT INTO questions (survey_id, position, type, prompt, options, required)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (survey_id, position, q["type"], q["prompt"],
                 json.dumps(q["options"]), q["required"]),
            )
        db.commit()
        flash("Survey updated.")
        return redirect(url_for("results", survey_id=survey_id, key=survey["secret"]))

    return render_template(
        "edit.html", survey=survey, questions=load_questions(survey_id), key=survey["secret"]
    )


@app.post("/s/<survey_id>/toggle")
def toggle_survey(survey_id: str) -> str:
    """Open or close a survey (stop accepting new responses)."""
    survey = get_survey_or_404(survey_id)
    check_secret(survey, request.values.get("key"))
    db = get_db()
    db.execute(
        "UPDATE surveys SET closed = ? WHERE id = ?",
        (0 if survey["closed"] else 1, survey_id),
    )
    db.commit()
    return redirect(url_for("results", survey_id=survey_id, key=survey["secret"]))


@app.post("/s/<survey_id>/delete")
def delete_survey(survey_id: str) -> str:
    """Permanently delete a survey and everything attached to it.

    All child tables use ``ON DELETE CASCADE``, so removing the survey
    row wipes questions, responses, and answers in one statement.
    """
    survey = get_survey_or_404(survey_id)
    check_secret(survey, request.values.get("key"))
    db = get_db()
    db.execute("DELETE FROM surveys WHERE id = ?", (survey_id,))
    db.commit()
    flash(f"Deleted “{survey['title']}”.")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Error handlers — friendly pages instead of raw tracebacks
# ---------------------------------------------------------------------------


@app.errorhandler(403)
def forbidden(_e) -> tuple[str, int]:
    """Rendered when the secret key is missing or wrong."""
    return render_template("error.html", code=403,
                           message="That secret key doesn't match this survey."), 403


@app.errorhandler(404)
def not_found(_e) -> tuple[str, int]:
    """Rendered for unknown survey ids."""
    return render_template("error.html", code=404,
                           message="No survey lives at this address."), 404


@app.errorhandler(400)
def bad_request(_e) -> tuple[str, int]:
    """Rendered when submitted data fails validation."""
    return render_template("error.html", code=400,
                           message="That submission didn't look right."), 400


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # ``init_db`` runs on every start; the schema uses IF NOT EXISTS so
    # existing data is untouched.
    init_db()
    # debug=True auto-reloads on code changes — turn off in production.
    app.run(debug=True)
