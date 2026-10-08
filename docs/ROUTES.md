# Routes

Every HTTP endpoint, who may call it, and what it expects.

Legend: 🔓 public · 🔒 requires the survey's secret key (`key` param)

---

## 🔓 `GET /`

The landing page and survey builder.

| | |
|---|---|
| Renders | `index.html` |
| Input | none |
| Notes | One question card is pre-rendered; JS clones more from a `<template>`. |

---

## 🔓 `POST /surveys`

Creates a new survey.

| Form field | Type | Notes |
|---|---|---|
| `title` | text | **required** (validated server-side) |
| `description` | text | optional |
| `q_type` | repeated | `choice` \| `text` \| `rating` — one per question, document order |
| `q_prompt` | repeated | question text, same order; blank entries skipped |
| `q_required` | repeated | value = card index of each *checked* "required" box |
| `q_options_N` | text | newline-separated options, only for choice question `N` |

**Responses**
- `200` → `created.html` with both links (public id + secret)
- `302` → back to the builder with a flash message (validation failure)

**Validation rules**
- title non-empty · ≥ 1 question · choice questions ≥ 2 unique options
- unknown `q_type` falls back to `text`

---

## 🔓 `GET /s/<survey_id>`

The public fill-in page.

| | |
|---|---|
| Renders | `take.html`, or `closed.html` if the survey is closed |
| 404 | unknown id |

---

## 🔓 `POST /s/<survey_id>`

Submits one anonymous response.

| Form field | Rules |
|---|---|
| `q<question_id>` | choice: must equal one of the stored options · rating: `"1"`–`"5"` · text: ≤ 5000 chars |
| required fields | missing → `302` back to the form with a flash message; **nothing recorded** |

**Responses**
- `200` → `thanks.html`
- `302` → form re-rendered with validation flash
- `403` → survey is closed
- `400` → structurally invalid value (e.g. rating `7`, unknown option)

**Not read from the request**: IP, cookies, `User-Agent`, referer —
see [ANONYMITY.md](ANONYMITY.md).

---

## 🔒 `GET /s/<survey_id>/results?key=…`

Results dashboard.

| | |
|---|---|
| Guard | `key` must match `surveys.secret` (constant-time compare) |
| Renders | `results.html` |
| 403 | missing/wrong key · 404 | unknown id |

Per-question output: choice → counts + percentages; rating → average +
histogram; text → the raw answers.

---

## 🔒 `GET|POST /s/<survey_id>/edit?key=…`

Edit form and its handler.

- **GET** → `edit.html`, pre-filled with current title/description/questions.
- **POST** → rewrites the survey. Same field names as `POST /surveys`
  (plus hidden `key`). Saving **replaces all questions**, which cascades
  into deleting answers attached to removed questions.

Redirects to the results page on success (`302`).

---

## 🔒 `POST /s/<survey_id>/toggle?key=…`

Flips `surveys.closed` (open ↔ closed). Always `302` → results page.
GET is not allowed — state changes must be POSTs so a pasted link or
prefetch can't trigger them.

---

## 🔒 `POST /s/<survey_id>/delete?key=…`

Permanently deletes the survey and, via `ON DELETE CASCADE`, all of its
questions, responses, and answers. `302` → home page with a confirmation
flash.

---

## Error pages

| Status | Handler |
|---|---|
| 400 | `error.html` — submission failed structural validation |
| 403 | `error.html` — wrong secret, or submission to a closed survey |
| 404 | `error.html` — unknown survey id |

---

## How the secret is passed

Accepted from **either** the query string or a form field — the routes
use `request.values`, which merges both:

```
GET  /s/abc/results?key=SECRET        ← bookmarks, copied links
POST /s/abc/edit   key=SECRET         ← hidden input in the edit form
```

This lets the secret ride along inside links (`results → edit → results`)
without re-prompting the creator.
