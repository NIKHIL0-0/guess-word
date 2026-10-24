
from flask import Flask

from db import get_db_connection

app = Flask(__name__)


@app.get("/")
def home():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), NOW()")
                database_name, server_time = cur.fetchone()

        return {
            "message": "Flask connected to Supabase successfully",
            "database": database_name,
            "server_time": server_time.isoformat(),
        }

    except Exception:
        app.logger.exception("Database connection failed")
        return {"error": "Database connection failed"}, 500


if __name__ == "__main__":
    app.run(debug=True)
