PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS surveys (
    id          TEXT PRIMARY KEY,
    secret      TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    closed      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id  TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    type       TEXT NOT NULL CHECK (type IN ('choice', 'text', 'rating')),
    prompt     TEXT NOT NULL,
    options    TEXT NOT NULL DEFAULT '[]',
    required   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS responses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id  TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    response_id INTEGER NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    value       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_questions_survey ON questions(survey_id, position);
CREATE INDEX IF NOT EXISTS idx_responses_survey ON responses(survey_id);
CREATE INDEX IF NOT EXISTS idx_answers_response ON answers(response_id);
