# anonymous-survey-taker

A small, self-contained web app for **hosting surveys and collecting fully
anonymous responses** — no accounts, no tracking, no identifying data.

Built with **Flask + SQLite** (Python standard-library `sqlite3`).

---

## What it does

| Feature | How it works |
|---|---|
| **Survey builder** | One page to write a title, description, and any number of questions. Three question types: **multiple choice**, **free text**, **1–5 rating**. Questions can be marked required. |
| **Anonymous public responses** | Every survey gets a public link (`/s/<id>`). Anyone with the link can respond — no login, ever. |
| **Results dashboard** | Every survey gets a secret link (`/s/<id>/results?key=…`) showing bar charts, star averages, and raw text answers. |
| **Edit / close / delete** | The same secret link guards an edit form, an open/close toggle, and permanent deletion. |
| **Zero identification** | IPs, cookies, user agents, and account ids are **never stored**. See [docs/ANONYMITY.md](docs/ANONYMITY.md). |

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install the single dependency
pip install -r requirements.txt

# 3. Run (creates survey.db automatically on first start)
python app.py
```

Open <http://127.0.0.1:5000>.

> The `.venv/` folder and `survey.db` are both listed in `.gitignore` —
> neither is ever committed.

---

## The two links

When you create a survey you immediately get two links:

```
Public link   http://127.0.0.1:5000/s/IC5XFlhC2-w
              └─ share this freely; respondents stay anonymous

Secret link   http://127.0.0.1:5000/s/IC5XFlhC2-w/results?key=ofangci7E-...
              └─ keep private; grants results + edit + close + delete
```

- The **public id** is random (`secrets.token_urlsafe(8)`).
- The **secret key** is longer and checked with a constant-time comparison.
- Lose the secret link → the survey is effectively orphaned (by design;
  there are no accounts to recover it with).

---

## Project layout

```
anonymous-survey-taker/
├── app.py                  # The entire backend: routes, DB, validation
├── schema.sql              # Database schema (applied on startup, idempotent)
├── requirements.txt        # Flask
├── .gitignore              # excludes .venv/ and survey.db
├── static/
│   └── style.css           # all styling, incl. CSS-only bar charts & stars
└── templates/
    ├── base.html           # shared layout + flash messages
    ├── index.html          # survey builder (JS clones question cards)
    ├── _question_card.html # one reusable question card (builder + editor)
    ├── created.html        # shows both links after creation
    ├── take.html           # public anonymous fill-in page
    ├── thanks.html         # post-submission confirmation
    ├── closed.html         # "survey no longer accepting responses"
    ├── results.html        # creator dashboard (charts)
    ├── edit.html           # creator edit form
    └── error.html          # 400 / 403 / 404 pages
```

---

## Documentation map

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Database schema, request flows, design decisions |
| [docs/ROUTES.md](docs/ROUTES.md) | Every HTTP route, its guards, and its inputs |
| [docs/ANONYMITY.md](docs/ANONYMITY.md) | Exactly what is — and is not — collected |
| [docs/TESTING.md](docs/TESTING.md) | How the app was verified + how to re-run the checks |

---

## A note on scope

This is a development-grade app: Flask's built-in server and a local SQLite
file. For a real deployment you'd put it behind a production WSGI server
(gunicorn/uwsgi), serve over HTTPS, and set `SECRET_KEY` from the
environment. The anonymity guarantees don't change — they're enforced by
what the code *doesn't* record.
