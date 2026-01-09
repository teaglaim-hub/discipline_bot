CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE NOT NULL,
    name TEXT,
    morning_time TEXT,
    checkin_time TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_morning_sent DATE,
    last_checkin_reminder_sent DATE,
    start_date DATE,
    timezone TEXT DEFAULT 'Europe/Moscow',
    best_streak_overall INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS focuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    domain TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    is_active INTEGER DEFAULT 1,
    best_streak INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    focus_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_text TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (focus_id) REFERENCES focuses(id)
);

-- Migration: добавить best_streak_overall если её нет
-- (будет выполнено в db.py при инициализации)
