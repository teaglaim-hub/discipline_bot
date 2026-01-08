import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        with open("models.sql", "r", encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()
    
    # Добавляем столбец timezone, если его нет
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Europe/Moscow'")
            await db.commit()
        except:
            pass  # столбец уже существует


async def get_user_by_tg_id(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        await cursor.close()
        return row


async def create_user(tg_id: int, name: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id, name) VALUES (?, ?)",
            (tg_id, name),
        )
        await db.commit()


async def update_user_name_and_time(
    tg_id: int,
    name: str,
    morning_time: str,
    checkin_time: str,
    start_date: str,
    last_morning_sent: str | None,
    last_checkin_reminder_sent: str | None,
    timezone: str = "Europe/Moscow",
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET
                name = ?,
                morning_time = ?,
                checkin_time = ?,
                start_date = ?,
                last_morning_sent = ?,
                last_checkin_reminder_sent = ?,
                timezone = ?
            WHERE tg_id = ?
            """,
            (name, morning_time, checkin_time, start_date,
             last_morning_sent, last_checkin_reminder_sent, timezone, tg_id),
        )
        await db.commit()

async def create_focus(user_tg_id: int, title: str, domain: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT id FROM users WHERE tg_id = ?", (user_tg_id,)
        )
        user = await cursor.fetchone()
        await cursor.close()
        if not user:
            return None

        # деактивируем предыдущий фокус
        await db.execute(
            """
            UPDATE focuses
            SET is_active = 0, ended_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND is_active = 1
            """,
            (user["id"],),
        )

        # создаём новый
        await db.execute(
            """
            INSERT INTO focuses (user_id, title, domain, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (user["id"], title, domain),
        )
        await db.commit()
        return True


async def get_active_focus_for_user(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT f.*
            FROM focuses f
            JOIN users u ON u.id = f.user_id
            WHERE u.tg_id = ? AND f.is_active = 1
            ORDER BY f.started_at DESC
            LIMIT 1
            """,
            (tg_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row


async def create_checkin_simple(tg_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # пользователь
        cursor = await db.execute("SELECT id, morning_time FROM users WHERE tg_id = ?", (tg_id,))
        user = await cursor.fetchone()
        await cursor.close()
        if not user:
            return False

        user_id = user["id"]

        # активный фокус
        cursor = await db.execute(
            """
            SELECT id FROM focuses
            WHERE user_id = ? AND is_active = 1
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        focus = await cursor.fetchone()
        await cursor.close()
        if not focus:
            return False

        focus_id = focus["id"]

                # сначала удаляем старый чек-ин за сегодня по этому фокусу (если был)
        await db.execute(
            """
            DELETE FROM checkins
            WHERE user_id = ?
              AND focus_id = ?
              AND date = DATE('now')
            """,
            (user_id, focus_id),
        )

        # новый чек-ин на сегодня
        await db.execute(
            """
            INSERT INTO checkins (user_id, focus_id, date, status)
            VALUES (?, ?, DATE('now'), ?)
            """,
            (user_id, focus_id, status),
        )

        # если чек-ин сделан до утреннего времени – помечаем, что утреннее на сегодня не нужно
        await db.execute(
            """
            UPDATE users
            SET last_morning_sent = DATE('now')
            WHERE id = ?
              AND (
                  morning_time IS NULL
                  OR time('now') <= morning_time
              )
            """,
            (user_id,),
        )

        await db.commit()
        return True

async def get_users_for_checkin(current_time_str: str):
    """
    current_time_str в формате 'HH:MM', например '21:30'.
    Возвращает пользователей, у которых время вечерних итогов совпадает.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE checkin_time = ?",
            (current_time_str,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

async def get_users_for_evening(today_str: str):
    """
    Берём всех пользователей, которые не получали вечернее сообщение сегодня.
    Сравнение времени будет делаться в Python с учётом timezone.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM users
            WHERE last_checkin_reminder_sent IS NULL OR last_checkin_reminder_sent <> ?
            """,
            (today_str,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

async def mark_evening_sent(user_ids: list[int], today_str: str):
    if not user_ids:
        return

    placeholders = ",".join("?" for _ in user_ids)
    params = [today_str] + user_ids

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""
            UPDATE users
            SET last_checkin_reminder_sent = ?
            WHERE id IN ({placeholders})
            """,
            params,
        )
        await db.commit()



async def get_users_for_morning(today_str: str):
    """
    Берём всех пользователей, которые не получали утреннее сообщение сегодня.
    Сравнение времени будет делаться в Python с учётом timezone.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM users
            WHERE last_morning_sent IS NULL OR last_morning_sent <> ?
            """,
            (today_str,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows

async def mark_morning_sent(user_ids: list[int], today_str: str):
    if not user_ids:
        return

    placeholders = ",".join("?" for _ in user_ids)
    params = [today_str] + user_ids

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""
            UPDATE users
            SET last_morning_sent = ?
            WHERE id IN ({placeholders})
            """,
            params,
        )
        await db.commit()


async def get_week_stats_for_user(tg_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # пользователь
        cursor = await db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = await cursor.fetchone()
        await cursor.close()
        if not user:
            return None

        # активный фокус + best_streak
        cursor = await db.execute(
            """
            SELECT id, title, best_streak FROM focuses
            WHERE user_id = ? AND is_active = 1
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user["id"],),
        )
        focus = await cursor.fetchone()
        await cursor.close()
        if not focus:
            return None

        focus_id = focus["id"]

        # агрегированная статистика за последние 7 дней
        cursor = await db.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count,
                SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) AS partial_count,
                SUM(CASE WHEN status = 'fail' THEN 1 ELSE 0 END) AS fail_count
            FROM checkins
            WHERE user_id = ?
              AND focus_id = ?
              AND date BETWEEN DATE('now', '-6 days') AND DATE('now')
            """,
            (user["id"], focus_id),
        )
        row = await cursor.fetchone()
        await cursor.close()

        stats = {
            "done": row["done_count"] or 0,
            "partial": row["partial_count"] or 0,
            "fail": row["fail_count"] or 0,
        }

        # статусы по дням за последние 7 дней (для текущего стрика)
        cursor = await db.execute(
            """
            SELECT date, status
            FROM checkins
            WHERE user_id = ?
              AND focus_id = ?
              AND date BETWEEN DATE('now', '-6 days') AND DATE('now')
            ORDER BY date DESC
            """,
            (user["id"], focus_id),
        )
        day_rows = await cursor.fetchall()
        await cursor.close()

        from datetime import datetime, timedelta

        today = datetime.now().date()
        day_status = {
            datetime.strptime(r["date"], "%Y-%m-%d").date(): r["status"]
            for r in day_rows
        }

        current_streak = 0
        d = today
        for _ in range(7):
            status = day_status.get(d)
            if status in ("done", "partial"):
                current_streak += 1
                d = d - timedelta(days=1)
            else:
                break

        best_streak = focus["best_streak"] or 0

        # если текущий стрик побил рекорд — обновляем в БД
        if current_streak > best_streak:
            best_streak = current_streak
            await db.execute(
                "UPDATE focuses SET best_streak = ? WHERE id = ?",
                (best_streak, focus_id),
            )
            await db.commit()

        # список статусов за последние 7 дней в порядке от старого к новому
        last_7_days_statuses = []
        d = today - timedelta(days=6)
        for _ in range(7):
            status = day_status.get(d)
            last_7_days_statuses.append(status)  # может быть None, done, partial, fail
            d = d + timedelta(days=1)

        return {
            "focus_title": focus["title"],
            "stats": stats,
            "streak": current_streak,
            "best_streak": best_streak,
            "last_7_days": last_7_days_statuses,
        }

async def get_streak_for_user(tg_id: int):
    """Текущий и лучший стрик по активному фокусу для /streak."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = await cursor.fetchone()
        await cursor.close()
        if not user:
            return None

        cursor = await db.execute(
            """
            SELECT id, title, best_streak FROM focuses
            WHERE user_id = ? AND is_active = 1
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (user["id"],),
        )
        focus = await cursor.fetchone()
        await cursor.close()
        if not focus:
            return None

        focus_id = focus["id"]

        # берём все даты и статусы по текущему фокусу
        cursor = await db.execute(
            """
            SELECT date, status
            FROM checkins
            WHERE user_id = ?
              AND focus_id = ?
            ORDER BY date DESC
            """,
            (user["id"], focus_id),
        )
        rows = await cursor.fetchall()
        await cursor.close()

        from datetime import datetime, timedelta

        if not rows:
            return {
                "focus_title": focus["title"],
                "current_streak": 0,
                "best_streak": focus["best_streak"] or 0,
            }

                # текущий стрик: идём от последнего дня с чек-ином назад
        day_status = {
            datetime.strptime(r["date"], "%Y-%m-%d").date(): r["status"]
            for r in rows
        }

        # последняя дата, где вообще был чек-ин по фокусу
        last_date = max(day_status.keys())

        current_streak = 0
        d = last_date
        while True:
            status = day_status.get(d)
            if status in ("done", "partial"):
                current_streak += 1
                d = d - timedelta(days=1)
            else:
                break


        best_streak = max(current_streak, focus["best_streak"] or 0)

        return {
            "focus_title": focus["title"],
            "current_streak": current_streak,
            "best_streak": best_streak,
        }



async def get_today_checkin_status(user_id: int, today_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT status
            FROM checkins
            WHERE user_id = ?
              AND date = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, today_str),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row["status"] if row else None


async def set_new_focus_for_user(tg_id: int, title: str, domain: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
        user = await cursor.fetchone()
        await cursor.close()
        if not user:
            return False

        user_id = user["id"]

        await db.execute(
            """
            UPDATE focuses
            SET is_active = 0, ended_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,),
        )

        await db.execute(
            """
            INSERT INTO focuses (user_id, title, domain, is_active)
            VALUES (?, ?, ?, 1)
            """,
            (user_id, title, domain),
        )

        await db.commit()
        return True