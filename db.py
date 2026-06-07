import sqlite3
from datetime import datetime, timezone

DB_FILE = "data/bot.db"

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    return conn

def setup():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_ids             TEXT NOT NULL,
            message                 TEXT NOT NULL,
            fire_at                 TEXT,
            cron_expr               TEXT,
            created_by              TEXT NOT NULL,
            roster_list             TEXT,
            advance_roster          INTEGER DEFAULT 1,
            last_run                TEXT,
            interval_days           INTEGER,
            interval_time           TEXT,
            interval_start          TEXT,
            interval_skip_weekday   INTEGER
        )
    """)
    for col, col_type in [
        ("last_run", "TEXT"),
        ("interval_days", "INTEGER"),
        ("interval_time", "TEXT"),
        ("interval_start", "TEXT"),
        ("interval_skip_weekday", "INTEGER"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE scheduled_messages ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_timezones (
            user_id  TEXT PRIMARY KEY,
            timezone TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_interactions (
            interaction_id  TEXT PRIMARY KEY,
            processed_at    TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deletion_log (
            deleted_id   INTEGER,
            deleted_at   TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS log_deletes
        BEFORE DELETE ON scheduled_messages
        BEGIN
            INSERT INTO deletion_log (deleted_id, deleted_at) VALUES (OLD.id, datetime('now'));
        END
    """)
    conn.commit()
    conn.close()

def add_message(channel_ids: list, message: str, fire_at: str, cron_expr: str, created_by: str,
                roster_list: str = None, advance_roster: bool = True,
                interval_days: int = None, interval_time: str = None,
                interval_start: str = None, interval_skip_weekday: int = None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scheduled_messages
            (channel_ids, message, fire_at, cron_expr, created_by, roster_list, advance_roster,
             interval_days, interval_time, interval_start, interval_skip_weekday)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(channel_ids), message, fire_at, cron_expr, created_by, roster_list, int(advance_roster),
          interval_days, interval_time, interval_start, interval_skip_weekday))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def claim_interaction(interaction_id: int) -> bool:
    """Insert interaction ID atomically. Returns False only on true duplicates."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_interactions (
                interaction_id  TEXT PRIMARY KEY,
                processed_at    TEXT NOT NULL
            )
        """)
        cursor.execute(
            "INSERT INTO processed_interactions (interaction_id, processed_at) VALUES (?, ?)",
            (str(interaction_id), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # genuine duplicate interaction
    except sqlite3.Error:
        return True  # unexpected DB error — let the command through
    finally:
        conn.close()

def get_all_messages():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_messages")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_message_last_run(message_id: int, last_run: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE scheduled_messages SET last_run = ? WHERE id = ?", (last_run, message_id))
    conn.commit()
    conn.close()

def row_exists(message_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM scheduled_messages WHERE id = ?", (message_id,))
    result = cursor.fetchone() is not None
    conn.close()
    return result

def delete_message(message_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scheduled_messages WHERE id = ?", (message_id,))
    cursor.execute("SELECT changes()")
    affected = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return affected > 0

def set_user_timezone(user_id: str, timezone: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_timezones (
            user_id  TEXT PRIMARY KEY,
            timezone TEXT NOT NULL
        )
    """)
    cursor.execute("""
        INSERT INTO user_timezones (user_id, timezone)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone
    """, (user_id, timezone))
    conn.commit()
    conn.close()

def get_user_timezone(user_id: str) -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_timezones (
            user_id  TEXT PRIMARY KEY,
            timezone TEXT NOT NULL
        )
    """)
    cursor.execute("SELECT timezone FROM user_timezones WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "UTC"