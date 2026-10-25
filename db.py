import os
import sqlite3
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()


class SQLiteCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._cursor.close()

    def execute(self, query, params=()):
        self._cursor.execute(query.replace("%s", "?"), params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class SQLiteConnection:
    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self._connection.rollback()
        else:
            self._connection.commit()
        self._connection.close()
        return False

    def cursor(self):
        return SQLiteCursor(self._connection.cursor())


def _get_sqlite_connection():
    path = Path(os.getenv("SQLITE_DATABASE", "instance/guess_word.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level="IMMEDIATE")
    conn.execute("PRAGMA foreign_keys = ON")
    return SQLiteConnection(conn)


def get_db_connection():
    """Use the Supabase pooler URL/settings unchanged, with optional dev SQLite."""
    url = os.getenv("DATABASE_URL")
    try:
        timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
    except ValueError as exc:
        raise ValueError("DB_CONNECT_TIMEOUT must be an integer") from exc
    if url:
        return psycopg.connect(url, connect_timeout=timeout, sslmode="require")
    settings = {key: os.getenv(key) for key in ("DB_HOST", "DB_USER", "DB_PASSWORD")}
    if all(settings.values()):
        try:
            return psycopg.connect(
                host=settings["DB_HOST"], port=os.getenv("DB_PORT", "5432"),
                dbname=os.getenv("DB_NAME", "postgres"), user=settings["DB_USER"],
                password=settings["DB_PASSWORD"], connect_timeout=timeout, sslmode="require",
            )
        except psycopg.Error:
            if os.getenv("DB_FALLBACK_SQLITE", "false").lower() != "true":
                raise
    elif os.getenv("DB_FALLBACK_SQLITE", "true").lower() != "true":
        raise ValueError("Set DATABASE_URL or DB_HOST, DB_USER, and DB_PASSWORD")
    return _get_sqlite_connection()


def ensure_schema():
    """Create the game tables when the existing Supabase schema is not yet migrated."""
    with get_db_connection() as conn:
        pg = isinstance(conn, psycopg.Connection)
        serial = "BIGSERIAL" if pg else "INTEGER"
        text_json = "JSONB" if pg else "TEXT"
        empty_json = "'[]'::jsonb" if pg else "'[]'"
        with conn.cursor() as cur:
            # Keep the application's richer state separate from the legacy
            # normalized `matches`/`games` tables already present in Supabase.
            cur.execute(f"""CREATE TABLE IF NOT EXISTS guess_word_matches (
                match_id {serial} PRIMARY KEY, userid INTEGER NOT NULL,
                secret_word VARCHAR(5) NOT NULL, status VARCHAR(12) NOT NULL DEFAULT 'active',
                guesses {text_json} NOT NULL DEFAULT {empty_json}, valid_guess_count INTEGER NOT NULL DEFAULT 0,
                is_fun_mode BOOLEAN NOT NULL DEFAULT FALSE, daily_date DATE NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            cur.execute("CREATE INDEX IF NOT EXISTS gw_matches_user_day ON guess_word_matches(userid, daily_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS gw_matches_rank ON guess_word_matches(secret_word, status, is_fun_mode)")
