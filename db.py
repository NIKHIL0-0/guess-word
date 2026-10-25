import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    """Open a secure PostgreSQL connection using Supabase settings."""
    database_url = os.getenv("DATABASE_URL")
    try:
        timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
    except ValueError as exc:
        raise ValueError("DB_CONNECT_TIMEOUT must be an integer") from exc

    if database_url:
        return psycopg.connect(
            database_url,
            connect_timeout=timeout,
            sslmode="require",
        )

    settings = {
        name: os.getenv(name)
        for name in ("DB_HOST", "DB_USER", "DB_PASSWORD")
    }
    if not all(settings.values()):
        raise ValueError("Set DATABASE_URL or DB_HOST, DB_USER, and DB_PASSWORD")

    return psycopg.connect(
        host=settings["DB_HOST"],
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "postgres"),
        user=settings["DB_USER"],
        password=settings["DB_PASSWORD"],
        connect_timeout=timeout,
        sslmode="require",
    )


def ensure_schema():
    """Create the application game table and indexes if needed."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS guess_word_matches (
                match_id BIGSERIAL PRIMARY KEY,
                userid INTEGER NOT NULL,
                secret_word VARCHAR(5) NOT NULL,
                status VARCHAR(12) NOT NULL DEFAULT 'active',
                guesses JSONB NOT NULL DEFAULT '[]'::jsonb,
                valid_guess_count INTEGER NOT NULL DEFAULT 0,
                is_fun_mode BOOLEAN NOT NULL DEFAULT FALSE,
                daily_date DATE NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS gw_matches_user_day "
            "ON guess_word_matches(userid, daily_date)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS gw_matches_rank "
            "ON guess_word_matches(secret_word, status, is_fun_mode)"
        )
        cur.execute(
            "UPDATE guess_word_matches SET status='lost', is_fun_mode=FALSE "
            "WHERE status='revealed'"
        )
