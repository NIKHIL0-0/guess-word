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
    """Verify that the normalized application tables are available."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name IN ('userinfo', 'games', 'guesses', 'matches', 'match_guesses')
            """
        )
        tables = {row[0] for row in cur.fetchall()}
    required = {"userinfo", "games", "guesses", "matches", "match_guesses"}
    missing = required - tables
    if missing:
        raise RuntimeError(
            "Missing normalized database tables: " + ", ".join(sorted(missing))
        )
