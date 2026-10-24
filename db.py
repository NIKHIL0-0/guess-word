import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    """Open a PostgreSQL connection using a URL or individual DB settings."""
    database_url = os.getenv("DATABASE_URL")
    connect_timeout = os.getenv("DB_CONNECT_TIMEOUT", "10")

    try:
        timeout = int(connect_timeout)
    except ValueError as exc:
        raise ValueError("DB_CONNECT_TIMEOUT must be an integer") from exc

    if database_url:
        return psycopg.connect(
            database_url,
            connect_timeout=timeout,
            sslmode="require",
        )

    required_settings = {
        "DB_HOST": os.getenv("DB_HOST"),
        "DB_USER": os.getenv("DB_USER"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD"),
    }
    missing_settings = [
        name for name, value in required_settings.items() if not value
    ]
    if missing_settings:
        raise ValueError(
            f"Missing database settings: {', '.join(missing_settings)}"
        )

    return psycopg.connect(
        host=required_settings["DB_HOST"],
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "postgres"),
        user=required_settings["DB_USER"],
        password=required_settings["DB_PASSWORD"],
        connect_timeout=timeout,
        sslmode="require",
    )
