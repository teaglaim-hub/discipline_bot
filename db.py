import sqlite3
from config import DB_PATH

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        with open('models.sql', 'r', encoding='utf-8') as f:
            db.executescript(f.read())
        db.commit()

def get_user_by_tg_id(tg_id: int):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = cursor.fetchone()
        cursor.close()
        return row

def create_user(tg_id: int, name: str = None):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT OR IGNORE INTO users (tg_id, name) VALUES (?, ?)", (tg_id, name))
        db.commit()

def update_user_name_and_time(tg_id: int, name: str, morning_time: str, checkin_time: str, start_date: str, last_morning_sent: str = None, last_checkin_reminder_sent: str = None):
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "UPDATE users SET name = ?, morning_time = ?, checkin_time = ?, start_date = ?, last_morning_sent = ?, last_checkin_reminder_sent = ? WHERE tg_id = ?",
            (name, morning_time, checkin_time, start_date, last_morning_sent, last_checkin_reminder_sent, tg_id)
        )
        db.commit()

def create_focus(tg_id: int, title: str, domain: str = None):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            return None
        
        user_id = user['id']
        
        db.execute("UPDATE focuses SET is_active = 0, ended_at = CURRENT_TIMESTAMP WHERE user_id = ? AND is_active = 1", (user_id,))
        db.execute("INSERT INTO focuses (user_id, title, domain, is_active) VALUES (?, ?, ?, 1)", (user_id, title, domain))
        db.commit()
        return True

def get_active_focus_for_user(tg_id: int):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute(
            "SELECT f.* FROM focuses f JOIN users u ON u.id = f.user_id WHERE u.tg_id = ? AND f.is_active = 1 ORDER BY f.started_at DESC LIMIT 1",
            (tg_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        return row

def create_checkin_simple(tg_id: int, status: str):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        
        cursor = db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            return False
        
        user_id = user['id']
        
        cursor = db.execute("SELECT id FROM focuses WHERE user_id = ? AND is_active = 1 ORDER BY started_at DESC LIMIT 1", (user_id,))
        focus = cursor.fetchone()
        cursor.close()
        
        if not focus:
            return False
        
        focus_id = focus['id']
        
        db.execute("DELETE FROM checkins WHERE user_id = ? AND focus_id = ? AND date = DATE('now')", (user_id, focus_id))
        db.execute("INSERT INTO checkins (user_id, focus_id, date, status) VALUES (?, ?, DATE('now'), ?)", (user_id, focus_id, status))
        db.commit()
        return True

def get_users_for_checkin(current_time_str: str):
    """current_time_str like '21:30'"""
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute("SELECT * FROM users WHERE checkin_time = ?", (current_time_str,))
        rows = cursor.fetchall()
        cursor.close()
        return rows

def get_users_for_evening(current_time_str: str, today_str: str):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute(
            "SELECT * FROM users WHERE checkin_time = ? AND (last_checkin_reminder_sent IS NULL OR last_checkin_reminder_sent != ?)",
            (current_time_str, today_str)
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows

def mark_evening_sent(user_ids: list, today_str: str):
    if not user_ids:
        return
    placeholders = ','.join('?' for _ in user_ids)
    params = [today_str] + user_ids
    with sqlite3.connect(DB_PATH) as db:
        db.execute(f"UPDATE users SET last_checkin_reminder_sent = ? WHERE id IN ({placeholders})", params)
        db.commit()

def get_users_for_morning(current_time_str: str, today_str: str):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute(
            "SELECT * FROM users WHERE morning_time = ? AND (last_morning_sent IS NULL OR last_morning_sent != ?)",
            (current_time_str, today_str)
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows

def mark_morning_sent(user_ids: list, today_str: str):
    if not user_ids:
        return
    placeholders = ','.join('?' for _ in user_ids)
    params = [today_str] + user_ids
    with sqlite3.connect(DB_PATH) as db:
        db.execute(f"UPDATE users SET last_morning_sent = ? WHERE id IN ({placeholders})", params)
        db.commit()

def get_week_stats_for_user(tg_id: int):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        
        cursor = db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            return None
        
        user_id = user['id']
        
        cursor = db.execute("SELECT id, title, best_streak FROM focuses WHERE user_id = ? AND is_active = 1 ORDER BY started_at DESC LIMIT 1", (user_id,))
        focus = cursor.fetchone()
        cursor.close()
        
        if not focus:
            return None
        
        focus_id = focus['id']
        
        cursor = db.execute(
            "SELECT SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done_count, SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) as partial_count, SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) as fail_count FROM checkins WHERE user_id = ? AND focus_id = ? AND date BETWEEN DATE('now', '-6 days') AND DATE('now')",
            (user_id, focus_id)
        )
        row = cursor.fetchone()
        cursor.close()
        
        stats = {
            'done': row['done_count'] or 0,
            'partial': row['partial_count'] or 0,
            'fail': row['fail_count'] or 0
        }
        
        cursor = db.execute(
            "SELECT date, status FROM checkins WHERE user_id = ? AND focus_id = ? AND date BETWEEN DATE('now', '-6 days') AND DATE('now') ORDER BY date DESC",
            (user_id, focus_id)
        )
        day_rows = cursor.fetchall()
        cursor.close()
        
        from datetime import datetime, timedelta
        today = datetime.now().date()
        day_status = {datetime.strptime(r['date'], '%Y-%m-%d').date(): r['status'] for r in day_rows}
        
        current_streak = 0
        d = today
        for _ in range(7):
            status = day_status.get(d)
            if status in ('done', 'partial'):
                current_streak += 1
                d = d - timedelta(days=1)
            else:
                break
        
        best_streak = focus['best_streak'] or 0
        if current_streak > best_streak:
            best_streak = current_streak
            db.execute("UPDATE focuses SET best_streak = ? WHERE id = ?", (best_streak, focus_id))
            db.commit()
        
        last_7_days_statuses = []
        d = today - timedelta(days=6)
        for _ in range(7):
            status = day_status.get(d)
            last_7_days_statuses.append(status or None)
            d = d + timedelta(days=1)
        
        return {
            'title': focus['title'],
            'stats': stats,
            'streak': current_streak,
            'best_streak': best_streak,
            'last_7_days': last_7_days_statuses
        }

def get_streak_for_user(tg_id: int):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        
        cursor = db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            return None
        
        user_id = user['id']
        
        cursor = db.execute("SELECT id, title, best_streak FROM focuses WHERE user_id = ? AND is_active = 1 ORDER BY started_at DESC LIMIT 1", (user_id,))
        focus = cursor.fetchone()
        cursor.close()
        
        if not focus:
            return None
        
        focus_id = focus['id']
        
        cursor = db.execute("SELECT date, status FROM checkins WHERE user_id = ? AND focus_id = ? ORDER BY date DESC", (user_id, focus_id))
        rows = cursor.fetchall()
        cursor.close()
        
        from datetime import datetime, timedelta
        
        if not rows:
            return {
                'title': focus['title'],
                'current_streak': 0,
                'best_streak': focus['best_streak'] or 0
            }
        
        day_status = {datetime.strptime(r['date'], '%Y-%m-%d').date(): r['status'] for r in rows}
        last_date = max(day_status.keys())
        
        current_streak = 0
        d = last_date
        while True:
            status = day_status.get(d)
            if status in ('done', 'partial'):
                current_streak += 1
                d = d - timedelta(days=1)
            else:
                break
        
        best_streak = max(current_streak, focus['best_streak'] or 0)
        
        return {
            'title': focus['title'],
            'current_streak': current_streak,
            'best_streak': best_streak
        }

def get_today_checkin_status(user_id: int):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute("SELECT status FROM checkins WHERE user_id = ? AND date = DATE('now') ORDER BY id DESC LIMIT 1", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        return row['status'] if row else None

def set_new_focus_for_user(tg_id: int, title: str, domain: str = None):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        cursor = db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = cursor.fetchone()
        cursor.close()
        
        if not user:
            return False
        
        user_id = user['id']
        
        db.execute("UPDATE focuses SET is_active = 0, ended_at = CURRENT_TIMESTAMP WHERE user_id = ? AND is_active = 1", (user_id,))
        db.execute("INSERT INTO focuses (user_id, title, domain, is_active) VALUES (?, ?, ?, 1)", (user_id, title, domain))
        db.commit()
        return True