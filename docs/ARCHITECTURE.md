# Architecture

How `anonymous-survey-taker` is put together: storage, request flows, and
the reasoning behind the notable choices.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | Flask 3.1 | Small surface area; the whole app is one file |
| Database | SQLite via stdlib `sqlite3` | Zero setup, single file, perfect for this scale |
| Templates | Jinja2 (bundled with Flask) | Server-rendered; the app works without JavaScript except for *building* surveys |
| Front-end JS | ~40 lines, inline | Only clones question cards in the builder — no framework |
| CSS | One stylesheet | Bar charts and star widgets are pure CSS (see below) |

There is **no ORM**. SQL lives directly in `app.py` next to the route that
uses it, and the schema lives in `schema.sql`.

---

## Database schema

Four tables (`schema.sql`):

```
surveys
├── id          TEXT PK      public URL id (random, url-safe)
├── secret      TEXT         creator key — guards results/edit/delete
├── title       TEXT
├── description TEXT
├── closed      INTEGER      0 = accepting responses, 1 = closed
└── created_at  TEXT         UTC timestamp

questions
├── id          INTEGER PK AUTOINCREMENT
├── survey_id   TEXT  → surveys.id  ON DELETE CASCADE
├── position    INTEGER       display order
├── type        TEXT          'choice' | 'text' | 'rating'
├── prompt      TEXT
├── options     TEXT          JSON array — only for 'choice'
└── required    INTEGER       0/1

responses                          ← one row per anonymous submission
├── id          INTEGER PK AUTOINCREMENT
├── survey_id   TEXT  → surveys.id  ON DELETE CASCADE
└── created_at  TEXT

answers
├── id          INTEGER PK AUTOINCREMENT
├── response_id INTEGER → responses.id ON DELETE CASCADE
├── question_id INTEGER → questions.id ON DELETE CASCADE
└── value       TEXT          the submitted answer
```

Key points:

- **Nothing links a response to a person.** The `responses` row has no IP,
  no session id, no user-agent — only the survey it belongs to and a date.
  See [ANONYMITY.md](ANONYMITY.md).
- **Everything cascades from `surveys`.** Deleting a survey wipes its
  questions, responses, and answers in a single statement
  (`PRAGMA foreign_keys = ON` is set per connection — SQLite ignores
  foreign keys otherwise).
- **Question options are JSON** in one column rather than a fifth table —
  options are only ever read as a whole list, never queried individually.

---

## Request flows

### 1. Create a survey

```
GET  /                     builder form (one question card pre-rendered)
POST /surveys              validate ──► insert survey ──► insert questions
                             │                              │
                             │  (on validation failure)    ▼
                             └── flash + redirect      created.html
                                                          shows BOTH links
```

- Validation happens **before** any insert; a bad submission never leaves
  partial data behind.
- The id and secret are generated with `secrets.token_urlsafe`.

### 2. Respond anonymously

```
GET  /s/<id>    render questions (or "closed" page)
POST /s/<id>    validate ALL answers ──► one transaction:
                    INSERT response ──► INSERT answers ──► thanks.html
```

- **Two-pass validation**: every answer is checked first (choice value ∈
  options, rating ∈ 1–5, required fields present, text ≤ 5000 chars);
  only then is anything written. Required-field failures re-render the
  form with a flash message instead of recording a partial response.
- Response + answers are written in **one transaction** — no orphans.

### 3. View results (secret required)

```
GET /s/<id>/results?key=…
    secret check (constant-time) ──► 403 if wrong
                                   ──► aggregate in SQL:
        answers grouped by (question_id, value)
                                   ──► render per question type:
        choice → bars with counts + %
        rating → average + 1..5 histogram
        text   → raw anonymous answers
```

### 4. Edit / close / delete

- **Edit** rewrites the question set: `UPDATE survey` → `DELETE questions`
  (cascade removes their answers) → re-`INSERT`. Straightforward and
  predictable; the UI warns that answers to removed questions are lost.
- **Close** flips `surveys.closed`. The public URL still resolves but
  shows "closed", and POSTs are rejected with `403`.
- **Delete** removes the survey row; cascades clean everything else.

---

## Notable design decisions

**Secret key instead of accounts.**
Anonymity and zero-friction creation both argue against user accounts.
The secret link *is* the credential: unguessable, revocable only by
losing it, and impossible to correlate with respondents (who never see it).

**Constant-time secret comparison.**
`secrets.compare_digest` prevents timing attacks that would otherwise
let an attacker guess the secret byte-by-byte.

**Server-rendered pages, minimal JS.**
Respondents get a plain HTML form — no scripts to fingerprint them, and
the survey works with JS disabled. JS exists only in the *creator* UI
(cloning question cards, copy-to-clipboard buttons).

**Aggregate results computed in Python.**
Answers are grouped with one `GROUP BY` query, then shaped per question
type in plain Python. At SQLite scale this is simpler and more readable
than SQL that emits chart-ready rows.

**`Row` subclass with attribute access.**
`sqlite3.Row` only supports `row["title"]`, but templates read better as
`survey.title`. The `Row` class in `app.py` adds `__getattr__` so both
styles work on the same objects.

**`from_json` Jinja filter.**
The `options` column is a JSON string; the filter (`parse_options`)
decodes it in templates (`q.options | from_json`) and degrades safely on
corrupt data.

---

## Error handling

| Code | Raised when | Page |
|---|---|---|
| 400 | Malformed submission (bad rating value, unknown choice, oversized text) | `error.html` |
| 403 | Wrong/missing secret, submission to a closed survey | `error.html` |
| 404 | Unknown survey id | `error.html` |

Handlers are registered with `@app.errorhandler` so no request ever
produces a raw traceback page (outside the debug console).

---

## Concurrency & scale

- One SQLite connection **per request** (Flask `g` scope), closed on
  teardown. SQLite handles concurrent readers fine; writes are serialized
  by the database itself — acceptable for a small survey tool.
- Aggregation loads all grouped rows into memory; fine for thousands of
  responses, not for millions. Swap to PostgreSQL + an ORM if you get there.
