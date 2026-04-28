"""
core/database.py — Shared SQLite setup for the BotHub platform.

WHY SQLITE:
SQLite is a file-based database — it needs no server, no installation,
and no configuration. The entire database is one file (bothub.db).
It's the right tool for a local tool like BotHub.

HOW IT WORKS:
  - get_connection() returns a live database connection.
  - init_db() creates all tables on first run (called once at app startup).
  - Each bot module's tables are defined here so the full schema is visible
    in one place.

WHAT IS row_factory:
  By default, sqlite3 returns rows as tuples: row[0], row[1] ...
  Setting row_factory = sqlite3.Row means rows behave like dicts:
  row["column_name"] — much more readable.
"""

import sqlite3
from datetime import datetime
from core.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Return an open connection to the shared BotHub SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # dict-like row access
    return conn


def init_db():
    """
    Create all database tables if they don't already exist.
    Safe to call every time the app starts — CREATE TABLE IF NOT EXISTS
    is a no-op when the table is already there.
    """
    conn = get_connection()
    c = conn.cursor()

    # ── Noosphere bot ────────────────────────────────────────────────────────
    # Stores tasks/to-dos sent via Telegram or the web UI.
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name  TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            detail      TEXT,
            status      TEXT    NOT NULL DEFAULT 'pending',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialised.")
