# Testing

The app has no test framework dependency — it was verified end-to-end
against a live server with `curl` and `sqlite3`. This page documents
what was checked and gives you a script to re-run it.

---

## Manual browser checklist

| # | Step | Expected |
|---|---|---|
| 1 | Open `/` | Builder renders with one question card |
| 2 | Click **+ Add question** | A new card appears; remove buttons work; options box only shows for *Multiple choice* |
| 3 | Submit with an empty title | Redirect back with "A survey needs a title." |
| 4 | Submit a choice question with 1 option | Redirect back with "Multiple-choice questions need at least 2 options." |
| 5 | Submit a valid survey | Page shows **both** links (public + secret) with copy buttons |
| 6 | Open the public link in a private window | Survey renders; no login prompt anywhere |
| 7 | Submit with a required field empty | Browser blocks (native `required`); server also re-prompts if bypassed |
| 8 | Submit a complete response | "Response recorded" page — no id, no redirect anywhere identifying |
| 9 | Open the secret link | Results show bars / star average / text answers matching the responses |
| 10 | Change one char in `?key=` | **403** page |
| 11 | Open results with no `key` at all | **403** page |
| 12 | **Edit survey** → change title, delete a question, save | Results reflect changes; answers to the deleted question are gone |
| 13 | **Close survey** → reopen public link | "closed and no longer accepting responses" |
| 14 | POST a response while closed (curl below) | **403**, nothing recorded |
| 15 | **Delete survey** → open public link | **404**; `survey.db` has no orphan rows |

---

## Automated smoke test

With the server running (`python app.py`), paste into a shell from the
project root:

```bash
#!/usr/bin/env bash
# Smoke test: create → respond → results → guard checks → delete.
set -e
BASE=http://127.0.0.1:5000

# --- create ------------------------------------------------------------
curl -s -o /tmp/created.html -w "create:         %{http_code} (want 200)\n" \
  -X POST $BASE/surveys \
  --data-urlencode "title=Smoke test" \
  --data-urlencode "q_type=choice" \
  --data-urlencode "q_prompt=Pick one" \
  --data-urlencode "q_options_0=Alpha
Beta" \
  --data-urlencode "q_type=rating" \
  --data-urlencode "q_prompt=Rate it" \
  --data-urlencode "q_required=1"

ID=$(grep -o '/s/[A-Za-z0-9_-]\{8,\}' /tmp/created.html | head -1 | cut -d/ -f3)
KEY=$(grep -o 'key=[A-Za-z0-9_-]\{10,\}' /tmp/created.html | head -1 | cut -d= -f2)
echo "id=$ID key=$KEY"

# question ids in display order
Q1=$(sqlite3 survey.db "SELECT id FROM questions WHERE survey_id='$ID' AND position=0")
Q2=$(sqlite3 survey.db "SELECT id FROM questions WHERE survey_id='$ID' AND position=1")

# --- take & respond ----------------------------------------------------
curl -s -o /dev/null -w "take (GET):       %{http_code} (want 200)\n" $BASE/s/$ID
curl -s -o /dev/null -w "respond:          %{http_code} (want 200)\n" \
  -X POST $BASE/s/$ID --data-urlencode "q$Q1=Alpha" --data-urlencode "q$Q2=5"

# required-field rejection must NOT record a response
BEFORE=$(sqlite3 survey.db "SELECT COUNT(*) FROM responses")
curl -s -o /dev/null -w "missing required: %{http_code} (want 302)\n" \
  -X POST $BASE/s/$ID --data-urlencode "q$Q1=Alpha"
AFTER=$(sqlite3 survey.db "SELECT COUNT(*) FROM responses")
echo "responses before/after: $BEFORE/$AFTER (must be equal)"

# --- access control ----------------------------------------------------
curl -s -o /dev/null -w "results valid:    %{http_code} (want 200)\n" "$BASE/s/$ID/results?key=$KEY"
curl -s -o /dev/null -w "results bad key:  %{http_code} (want 403)\n"  "$BASE/s/$ID/results?key=wrong"
curl -s -o /dev/null -w "results no key:   %{http_code} (want 403)\n"  "$BASE/s/$ID/results"
curl -s -o /dev/null -w "unknown survey:   %{http_code} (want 404)\n"  $BASE/s/doesnotex

# --- close / reopen / delete ------------------------------------------
curl -s -o /dev/null -w "close:            %{http_code} (want 302)\n" -X POST $BASE/s/$ID/toggle --data-urlencode "key=$KEY"
curl -s -o /dev/null -w "respond while closed: %{http_code} (want 403)\n" -X POST $BASE/s/$ID --data-urlencode "q$Q1=Alpha"
curl -s -o /dev/null -w "delete bad key:   %{http_code} (want 403)\n" -X POST $BASE/s/$ID/delete --data-urlencode "key=nope"
curl -s -o /dev/null -w "delete valid:     %{http_code} (want 302)\n" -X POST $BASE/s/$ID/delete --data-urlencode "key=$KEY"
echo "leftover rows — surveys/questions/responses/answers:"
sqlite3 survey.db "SELECT (SELECT COUNT(*) FROM surveys), (SELECT COUNT(*) FROM questions), (SELECT COUNT(*) FROM responses), (SELECT COUNT(*) FROM answers)"
echo "(all four must be 0 if this was the only survey)"
```

---

## Results of the verification run

| Check | Result |
|---|---|
| Create survey (3 questions: choice/rating/text) | ✅ 200 |
| Public page renders (8 radios = 3 choices + 5 stars) | ✅ 200 |
| Anonymous response × 2 recorded | ✅ 200 each |
| Missing required rating → re-prompt, **no** row written | ✅ 302, count unchanged |
| Results: bar fills, star average `4.5`, text answers shown | ✅ 200 |
| Results with wrong key / no key | ✅ 403 / 403 |
| Unknown survey id | ✅ 404 |
| Edit (retitle + question rewrite) | ✅ applied to DB |
| Close → public page shows closed banner; POST rejected | ✅ 302 / 403 |
| Toggle & delete with wrong key | ✅ 403 |
| Delete with valid key → zero orphan rows anywhere | ✅ cascade clean |

---

## Re-running after changes

The server runs with `debug=True`, so **code changes auto-restart**;
template and CSS changes reload per request. For a clean slate:

```bash
rm -f survey.db      # wipe all data — next start recreates the schema
python app.py        # (inside the activated .venv)
```
