# Anonymity

What "anonymous" means in this app — precisely — and the trade-offs that
come with it.

---

## What is *never* collected

The response-handling code (`POST /s/<survey_id>` in `app.py`) reads only
form fields named `q<question_id>`. It deliberately ignores everything
else about the request:

| Data | Status |
|---|---|
| IP address | **never read, never stored** |
| Cookies / session ids | no session is created for respondents |
| `User-Agent` / browser fingerprint | never read |
| `Referer` header | never read |
| Login / email / name | no accounts exist |
| Per-answer timestamps | not stored (only the response's coarse date) |
| Precise geolocation | never requested |

There is also **no third-party anything** — no analytics, no fonts CDN,
no error tracking. The page loads exactly one resource: the local
stylesheet. Nothing phones home.

---

## What *is* stored per response

For each submission, exactly two kinds of rows:

```
responses:  id (sequential), survey_id, created_at (date only)
answers:    response_id, question_id, value   ← the answer itself
```

- `response_id` groups the answers of one submission. It is an ordinary
  auto-increment integer that is **never shown to the respondent** and
  carries no personal data — you cannot look it up and learn who made it.
- `created_at` is a plain UTC date (`datetime('now')`) so the creator can
  tell *that* responses arrived, not *who* sent them.

Nothing in these rows can be joined against a person. Even a full
database disclosure reveals only: which survey, which answers, which day.

---

## How respondents stay unlinkable

1. **No credential to correlate.** Respondents never authenticate, so
   there is no account, token, or cookie tying their answers to them.
2. **The creator can't identify them either.** The results page shows
   aggregates (and raw text answers *as typed*) — if a respondent writes
   something identifying in a free-text box, that's their own choice;
   the app doesn't add anything.
3. **Two links, one wall.** The secret results link is never included in
   the public page's HTML — respondents can't see it, so holding the
   public link grants zero extra access.

---

## Honest limitations

Anonymous by construction ≠ anonymous under all threat models:

- **Free text can self-identify.** "As the only backend engineer…" —
  the app stores what people write verbatim. Survey *instructions* are
  the right place to warn respondents about this.
- **Timing correlation.** If exactly one response arrives at 03:00:07,
  an observer with access to server logs (not the database) could
  guess. The app itself stores only a date; web-server access logs are
  a deployment concern — disable or truncate them for strong anonymity.
- **Network-level observers.** Anyone watching the wire sees who visits
  which URL. Deploy behind **HTTPS**, and consider a reverse proxy that
  strips headers if that's in your threat model.
- **The secret key identifies the creator,** not respondents. Keep it
  private and the two populations stay disjoint.

---

## Design rules that keep it this way

If you extend the app, keep these invariants (they're easy to violate):

1. **Never log or store request metadata** in the responses path —
   no `request.remote_addr`, no `request.user_agent`, no `request.headers`.
2. **Never add a session/cookie for respondents.** Flash messages on the
   public flow use a short-lived session cookie *only* when validation
   fails, and it contains no respondent data.
3. **Never return a response id to the submitter.** The `thanks.html`
   page links nowhere near the submission.
4. **Don't add analytics "just to see usage."** Counting responses is
   already done in-database for the creator; page-view tracking is not
   needed and breaks the promise above.
