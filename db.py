import sqlite3

DB_FILE = "data/bot.db"

def get_connection():
    return sqlite3.connect(DB_FILE)

def setup():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_ids     TEXT NOT NULL,
            message         TEXT NOT NULL,
            fire_at         TEXT,
            cron_expr       TEXT,
            created_by      TEXT NOT NULL,
            roster_list     TEXT,
            advance_roster  INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_jobs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_ids     TEXT NOT NULL,
            message         TEXT NOT NULL,
            hour            INTEGER NOT NULL,
            minute          INTEGER NOT NULL,
            saturday_hour   INTEGER NOT NULL,
            saturday_minute INTEGER NOT NULL,
            start_date      TEXT,
            last_run        TEXT,
            created_by      TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_timezones (
            user_id  TEXT PRIMARY KEY,
            timezone TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def add_message(channel_ids: list, message: str, fire_at: str, cron_expr: str, created_by: str, roster_list: str = None, advance_roster: bool = True):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scheduled_messages (channel_ids, message, fire_at, cron_expr, created_by, roster_list, advance_roster)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(channel_ids), message, fire_at, cron_expr, created_by, roster_list, int(advance_roster)))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def get_all_messages():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_messages")
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_message(message_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scheduled_messages WHERE id = ?", (message_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def add_custom_job(channel_ids: list, message: str, hour: int, minute: int, saturday_hour: int, saturday_minute: int, created_by: str, start_date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO custom_jobs (channel_ids, message, hour, minute, saturday_hour, saturday_minute, start_date, last_run, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
    """, (str(channel_ids), message, hour, minute, saturday_hour, saturday_minute, start_date, created_by))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id

def get_all_custom_jobs():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM custom_jobs")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_custom_job_last_run(job_id: int, last_run: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE custom_jobs SET last_run = ? WHERE id = ?", (last_run, job_id))
    conn.commit()
    conn.close()

def delete_custom_job(job_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_jobs WHERE id = ?", (job_id,))
    conn.commit()
    affected = cursor.rowcount
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