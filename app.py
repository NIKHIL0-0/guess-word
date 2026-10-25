import json
import os
import random
import re
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

import psycopg
from flask import Flask, jsonify, redirect, render_template, request, session
from flask_session import Session
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from psycopg.errors import UniqueViolation
from werkzeug.security import check_password_hash, generate_password_hash

from db import ensure_schema, get_db_connection

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-key-change-me"),
    SESSION_TYPE="filesystem", SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
    SESSION_COOKIE_SAMESITE="Lax", SESSION_USE_SIGNER=True,
)
os.makedirs(app.instance_path, exist_ok=True)
app.config["SESSION_FILE_DIR"] = os.path.join(app.instance_path, "flask_session")
Session(app)
csrf = CSRFProtect(app)

# A bundled, deliberately conservative word list. It can be replaced by WORD_LIST_FILE.
WORDS = set("""adore agile alarm alder alert alien align alive alone altar ample angry ankle apple arena argue arise array audio audit avoid award bacon badge baker basic beach beard began begin being below bench berry birth black blame blind block bloom board brain brand brave bread break brick bring broad brown brush build built cable carry catch cause chain chair chalk charm chase cheap check chest chief child chose civil claim class clean clear click climb clock close cloud coach coast coral could count court cover craft crash crazy cream crisp cross crowd crown crude cruel curry cycle daily dairy dance dealt death delay delta debut depth devil dirty doubt dozen draft drama dream dress drink drive eager early earth eight elbow elder elect elite empty enjoy enter entry equal error event every exact exist extra faith false fancy fatal fault favor feast fence fewer field fifth fifty fight final first flame flash fleet floor flour focus force forth forty found frame fresh front frost fruit funny ghost giant given glass globe glory grace grade grain grand grant grape graph grasp grass great green greet grief grind gross group guard guess guide habit happy harsh heart heavy hello hence hotel house human humor ideal image imply index inner input irony issue ivory judge juice juicy knife knock label labor laser later laugh layer learn least leave legal lemon level light limit linen liver local logic loose lucky lunar lunch magic major maker maple march marry match maybe medal media mercy merry metal meter might minor model money month moral motor mount mouse mouth movie music naive nerve never newly night noise north novel nurse occur ocean offer often olive onset opera orbit order other ought outer paint panel panic paper party pasta patch pause peace peach pearl penny phone photo piano piece pilot pitch place plain plane plant plate plead plenty point pound power press price pride prime print prize proof proud prove queen quick quiet radar raise range rapid ratio reach react ready realm reply right rigid rival river robot rocky rough round route royal rural saint salad scale scare scene scope score scout screw sense serve seven shadow shake shame shape share sharp sheep shelf shell shift shine shirt shock shoot shore short shout sight since sixth sixty skate skill skirt skull sleep slice slide slope small smart smile smoke solid solve sorry sound south space spare speak speed spell spend spent spice split spoke sport spray squad stack staff stage stair stake stale stand start state steak steal steam steel steep steer stick still stock stone stood store storm story stove straw strip stuck study style sugar suite super swear sweet swing table taken taste teach teeth thank their theme there these thick thing third those three throw tiger tight tired title toast today topic total touch tough tower toxic trace track trade trail train treat trend trial tribe trick tried truck truly trust truth twice uncle under union unity until upper upset urban usage usual valid value video visit vital voice waste watch water wheel where which white whole whose woman world worry would write wrong yield young youth""".split())
WORD_LIST = set(os.getenv("WORD_LIST_FILE", "") and open(os.getenv("WORD_LIST_FILE")).read().split() or WORDS)
WORD_LIST = {w.strip().lower() for w in WORD_LIST if re.fullmatch(r"[a-zA-Z]{5}", w.strip())}
TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "UTC"))


def error(message, status=400):
    return jsonify(error=message), status


def body():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def auth(required=True):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if required and not session.get("userid"):
                return error("Authentication required.", 401)
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def admin_only(fn):
    @wraps(fn)
    @auth()
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            return error("Administrator access required.", 403)
        return fn(*args, **kwargs)
    return wrapped


def today():
    return datetime.now(TZ).date()


def row_dict(row, fields):
    return dict(zip(fields, row)) if row else None


def parse_guesses(value):
    if isinstance(value, list):
        return value
    try:
        return json.loads(value or "[]")
    except (TypeError, ValueError):
        return []


def feedback(guess, secret):
    result = ["absent"] * 5
    remaining = {}
    for i, (g, s) in enumerate(zip(guess, secret)):
        if g == s:
            result[i] = "correct"
        else:
            remaining[s] = remaining.get(s, 0) + 1
    for i, g in enumerate(guess):
        if result[i] == "correct":
            continue
        if remaining.get(g, 0):
            result[i] = "present"
            remaining[g] -= 1
    return result


@app.errorhandler(CSRFError)
def csrf_error(_):
    return error("CSRF token missing or invalid.", 400)


@app.errorhandler(psycopg.Error)
def database_error(exc):
    app.logger.exception("Unhandled request failure", exc_info=exc)
    return error("Database temporarily unavailable.", 503)


@app.get("/api/auth/csrf")
def csrf_token():
    return jsonify(csrf_token=generate_csrf())


@app.post("/api/auth/register")
def register():
    data = body(); username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return error("Username and password are required.")
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{5,50}", username):
        return error("Username must be 5-50 characters using letters, numbers, and underscores only.")
    if len(password) < 5 or not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password) or not re.search(r"[$%*]", password):
        return error("Password must contain 5+ chars, a letter, a number, and $, %, or *.")
    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO userinfo (username,password_hash) VALUES (%s,%s) RETURNING userid,username,role",
                        (username, generate_password_hash(password)))
            user = cur.fetchone()
    except UniqueViolation:
        return error("Username is already taken.", 409)
    return jsonify(user=row_dict(user, ("userid", "username", "role"))), 201


@app.post("/api/auth/login")
def login():
    data = body()
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT userid,username,password_hash,role FROM userinfo WHERE username=%s", (str(data.get("username", "")).strip(),))
        user = cur.fetchone()
    if not user or not check_password_hash(user[2], str(data.get("password", ""))):
        return error("Invalid username or password.", 401)
    session.clear(); session.update(userid=user[0], username=user[1], role=user[3]); session.permanent = True
    return jsonify(user=row_dict(user, ("userid", "username", "role")))


@app.post("/api/auth/logout")
@auth()
def logout():
    session.clear()
    return jsonify(message="Logout successful.")


@app.get("/api/auth/me")
@auth()
def me():
    return jsonify(user={"userid": session["userid"], "username": session["username"], "role": session["role"]})


def match_json(row):
    fields = ("match_id", "secret_word", "status", "guesses", "valid_guess_count", "is_fun_mode", "started_at", "completed_at")
    item = row_dict(row, fields)
    item["guesses"] = parse_guesses(item["guesses"])
    item["feedback"] = [
        feedback(guess, item["secret_word"]) for guess in item["guesses"]
    ]
    if item["status"] == "lost" and not item["is_fun_mode"]:
        item["answer"] = item["secret_word"]
    item.pop("secret_word", None)
    return item


@app.get("/api/matches")
@auth()
def matches():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT match_id,secret_word,status,guesses,valid_guess_count,is_fun_mode,started_at,completed_at FROM guess_word_matches WHERE userid=%s ORDER BY created_at DESC", (session["userid"],))
        return jsonify(matches=[match_json(row) for row in cur.fetchall()])


@app.post("/api/matches")
@auth()
def start_match():
    day = today()
    with get_db_connection() as conn, conn.cursor() as cur:
        if isinstance(conn, psycopg.Connection):
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (int(session["userid"]),),
            )
        cur.execute(
            "SELECT COUNT(*) FROM guess_word_matches "
            "WHERE userid=%s AND daily_date=%s",
            (session["userid"], day),
        )
        if cur.fetchone()[0] >= 3:
            return error("Maximum of 3 new matches per day reached.", 429)
        secret = random.choice(tuple(WORD_LIST))
        cur.execute("INSERT INTO guess_word_matches(userid,secret_word,daily_date,guesses) VALUES (%s,%s,%s,%s) RETURNING match_id,secret_word,status,guesses,valid_guess_count,is_fun_mode,started_at,completed_at",
                    (session["userid"], secret, day, json.dumps([])))
        return jsonify(match=match_json(cur.fetchone())), 201


@app.get("/api/matches/<int:match_id>")
@auth()
def status(match_id):
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT match_id,secret_word,status,guesses,valid_guess_count,is_fun_mode,started_at,completed_at FROM guess_word_matches WHERE match_id=%s AND userid=%s", (match_id, session["userid"]))
        row = cur.fetchone()
    if not row: return error("Match not found.", 404)
    return jsonify(match=match_json(row))


@app.post("/api/matches/<int:match_id>/resume")
@auth()
def resume(match_id):
    """Explicit resume endpoint; ownership is enforced by the same status query."""
    return status(match_id)


@app.post("/api/matches/<int:match_id>/guess")
@auth()
def guess(match_id):
    value = body().get("guess")
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z]{5}", value):
        return error("Guess must be five letters.")
    value = value.lower()
    if value not in WORD_LIST:
        return error("That is not a valid English word.", 422)
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT secret_word,status,guesses,valid_guess_count,is_fun_mode,started_at "
            "FROM guess_word_matches WHERE match_id=%s AND userid=%s FOR UPDATE",
            (match_id, session["userid"]),
        )
        row = cur.fetchone()
        if not row: return error("Match not found.", 404)
        secret, state, old, count, fun, started = row
        guesses = parse_guesses(old)
        if state != "active" and not (state == "lost" and fun):
            return error("Match is already complete.", 409)
        guesses.append(value); count += 1
        won = value == secret
        exhausted = count >= 5 and not fun
        # A standard loss deliberately becomes an unlimited, non-competitive fun game.
        new_state = "won" if won and not fun else ("lost" if fun or exhausted else "active")
        cur.execute("UPDATE guess_word_matches SET guesses=%s,valid_guess_count=%s,status=%s,completed_at=CASE WHEN %s <> 'active' THEN CURRENT_TIMESTAMP ELSE completed_at END,is_fun_mode=CASE WHEN %s AND %s THEN TRUE ELSE is_fun_mode END WHERE match_id=%s AND userid=%s",
                    (json.dumps(guesses), count, new_state, new_state, exhausted, fun, match_id, session["userid"]))
        result = {
            "guess": value,
            "feedback": feedback(value, secret),
            "status": new_state,
            "attempt": count,
        }
        if won and fun:
            result["fun_solved"] = True
        if exhausted and not won and not fun:
            cur.execute("UPDATE guess_word_matches SET is_fun_mode=TRUE WHERE match_id=%s AND userid=%s", (match_id, session["userid"]))
            result["status"] = "fun"
        if won and not fun:
            result["ranking"] = ranking(cur, secret, started, count, match_id)
        return jsonify(result)


def ranking(cur, secret, started, count, current_match_id):
    cur.execute(
        """
        SELECT started_at, completed_at, valid_guess_count
        FROM guess_word_matches
        WHERE secret_word=%s
          AND status='won'
          AND is_fun_mode=FALSE
          AND match_id<>%s
        """,
        (secret, current_match_id),
    )
    rows = cur.fetchall()
    def seconds(start, end):
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if isinstance(end, str):
            end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (end - start).total_seconds() if start and end else float("inf")
    current_key = (seconds(started, datetime.now(started.tzinfo) if hasattr(started, "tzinfo") else datetime.now()), count)
    keys = [(seconds(s, e), n) for s, e, n in rows]
    rank = 1 + sum(1 for key in keys if key < current_key)
    population = len(rows) + 1
    better_than = round(100 * (population - rank) / population, 2)
    return {
        "rank": rank,
        "total_population": population,
        "percentile": better_than,
        "top_percentage": round(100 * rank / population, 2),
    }


@app.post("/api/matches/<int:match_id>/reveal")
@auth()
def reveal(match_id):
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE guess_word_matches SET status='lost',is_fun_mode=FALSE,completed_at=COALESCE(completed_at,CURRENT_TIMESTAMP) WHERE match_id=%s AND userid=%s RETURNING secret_word,status", (match_id, session["userid"]))
        row = cur.fetchone()
    if not row: return error("Match not found.", 404)
    return jsonify(secret=row[0], status=row[1])


@app.get("/api/admin/reports/daily")
@admin_only
def daily_report():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT daily_date,
                   COUNT(DISTINCT userid),
                   SUM(valid_guess_count),
                   SUM(CASE WHEN status='won' AND is_fun_mode=FALSE THEN 1 ELSE 0 END)
            FROM guess_word_matches
            GROUP BY daily_date
            ORDER BY daily_date DESC
        """)
        return jsonify(report=[
            {
                "date": str(r[0]),
                "users": r[1],
                "guesses": r[2] or 0,
                "correct_guesses": r[3] or 0,
            }
            for r in cur.fetchall()
        ])


@app.get("/api/admin/reports/words")
@admin_only
def word_report():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT secret_word,
                   COUNT(*) AS matches,
                   SUM(valid_guess_count) AS guesses,
                   SUM(CASE WHEN status='won' AND is_fun_mode=FALSE THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status='lost' THEN 1 ELSE 0 END) AS losses
            FROM guess_word_matches
            GROUP BY secret_word
            ORDER BY secret_word
        """)
        return jsonify(report=[
            {
                "word": r[0],
                "matches": r[1],
                "guesses": r[2] or 0,
                "wins": r[3] or 0,
                "losses": r[4] or 0,
                "win_rate": round((r[3] or 0) * 100 / r[1], 2) if r[1] else 0,
            }
            for r in cur.fetchall()
        ])


@app.get("/api/admin/reports/users")
@admin_only
def user_report():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.daily_date, m.userid, u.username,
                   SUM(m.valid_guess_count),
                   SUM(CASE WHEN m.status='won' AND m.is_fun_mode=FALSE
                            THEN 1 ELSE 0 END)
            FROM guess_word_matches AS m
            JOIN userinfo AS u ON u.userid=m.userid
            GROUP BY m.daily_date, m.userid, u.username
            ORDER BY m.daily_date DESC, u.username
            """
        )
        return jsonify(
            report=[
                {
                    "date": str(row[0]),
                    "userid": row[1],
                    "username": row[2],
                    "words_tried": row[3] or 0,
                    "correct_guesses": row[4] or 0,
                }
                for row in cur.fetchall()
            ]
        )


@app.get("/")
def home():
    if not session.get("userid"):
        return redirect("/login")
    return redirect("/admin" if session.get("role") == "admin" else "/game")


@app.get("/login")
def login_page():
    if session.get("userid"):
        return redirect("/admin" if session.get("role") == "admin" else "/game")
    return render_template("login.html")


@app.get("/game")
def game_page():
    if not session.get("userid"):
        return redirect("/login")
    if session.get("role") == "admin":
        return redirect("/admin")
    return render_template("game.html")


@app.get("/admin")
def admin_page():
    if not session.get("userid"):
        return redirect("/login")
    if session.get("role") != "admin":
        return redirect("/game")
    return render_template("admin.html")


with app.app_context():
    ensure_schema()

if __name__ == "__main__":
    app.run(debug=True)
