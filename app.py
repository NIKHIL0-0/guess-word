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


def match_json(row, guess_rows):
    fields = (
        "match_id", "game_id", "secret_word", "status", "valid_guess_count",
        "is_fun_mode", "answer_revealed", "solved_in_fun_mode", "started_at",
        "completed_at",
    )
    item = row_dict(row, fields)
    item["guesses"] = [guess[0] for guess in guess_rows]
    item["feedback"] = [guess[1] for guess in guess_rows]
    if item["status"] == "won" and item["is_fun_mode"]:
        item["status"] = "lost"
    if item["status"] == "won" or item["answer_revealed"] or item["solved_in_fun_mode"]:
        item["answer"] = item["secret_word"]
    item.pop("secret_word", None)
    return item


def load_match(cur, match_id, userid):
    cur.execute(
        """
        SELECT m.matchid, m.gameid, g.gameword, m.status,
               COUNT(mg.turn), m.is_fun_mode, m.answer_revealed,
               m.solved_in_fun_mode, m.started_at, m.completed_at
        FROM matches AS m
        JOIN games AS g ON g.gameid=m.gameid
        LEFT JOIN match_guesses AS mg ON mg.matchid=m.matchid
        WHERE m.matchid=%s AND m.userid=%s
        GROUP BY m.matchid, g.gameword
        """,
        (match_id, userid),
    )
    row = cur.fetchone()
    if not row:
        return None
    cur.execute(
        """
        SELECT g.guessword, mg.feedback
        FROM match_guesses AS mg
        JOIN guesses AS g ON g.guessid=mg.guessid
        WHERE mg.matchid=%s
        ORDER BY mg.turn
        """,
        (match_id,),
    )
    return match_json(row, cur.fetchall())


@app.get("/api/matches")
@auth()
def matches():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT matchid FROM matches WHERE userid=%s ORDER BY started_at DESC",
            (session["userid"],),
        )
        match_ids = [row[0] for row in cur.fetchall()]
        return jsonify(matches=[
            load_match(cur, match_id, session["userid"]) for match_id in match_ids
        ])


@app.post("/api/matches")
@auth()
def start_match():
    day = today()
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(session["userid"]),))
        cur.execute(
            "SELECT COUNT(*) FROM matches "
            "WHERE userid=%s AND daily_date=%s",
            (session["userid"], day),
        )
        if cur.fetchone()[0] >= 3:
            return error("Maximum of 3 new matches per day reached.", 429)
        cur.execute(
            """
            SELECT gameid, gameword
            FROM games
            WHERE gameid NOT IN (
                SELECT gameid FROM matches WHERE userid=%s
            )
            ORDER BY random()
            LIMIT 1
            """,
            (session["userid"],),
        )
        game = cur.fetchone()
        if not game:
            return error("No new words are available for this user.", 409)
        cur.execute(
            """
            INSERT INTO matches (gameid, userid, daily_date)
            VALUES (%s, %s, %s)
            RETURNING matchid
            """,
            (game[0], session["userid"], day),
        )
        match_id = cur.fetchone()[0]
        return jsonify(match=load_match(cur, match_id, session["userid"])), 201


@app.get("/api/matches/<int:match_id>")
@auth()
def status(match_id):
    with get_db_connection() as conn, conn.cursor() as cur:
        match = load_match(cur, match_id, session["userid"])
    if not match: return error("Match not found.", 404)
    return jsonify(match=match)


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
    value = value.upper()
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT guessid FROM guesses WHERE guessword=%s", (value,))
        guess_row = cur.fetchone()
        if not guess_row:
            return error("That is not a valid English word.", 422)
        cur.execute(
            """
            SELECT m.gameid, g.gameword, m.status, m.is_fun_mode,
                   m.solved_in_fun_mode, m.started_at
            FROM matches AS m
            JOIN games AS g ON g.gameid=m.gameid
            WHERE m.matchid=%s AND m.userid=%s
            FOR UPDATE OF m
            """,
            (match_id, session["userid"]),
        )
        row = cur.fetchone()
        if not row:
            return error("Match not found.", 404)
        game_id, secret, state, fun, solved_fun, started = row
        cur.execute(
            "SELECT COUNT(*) FROM match_guesses WHERE matchid=%s",
            (match_id,),
        )
        count = cur.fetchone()[0]
        if state != "ongoing" and not (state == "lost" and fun):
            return error("Match is already complete.", 409)
        turn = count + 1
        won = value == secret
        exhausted = turn >= 5 and not fun and not won
        new_status = "won" if won and not fun else ("lost" if fun or exhausted else "ongoing")
        is_fun_mode = fun or exhausted
        solved_in_fun_mode = solved_fun or (won and fun)
        feedback_value = feedback(value.lower(), secret.lower())
        cur.execute(
            """
            INSERT INTO match_guesses
                (matchid, turn, guessid, feedback, correct_letters, partial_correct_letters)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                match_id, turn, guess_row[0], json.dumps(feedback_value),
                feedback_value.count("correct"), feedback_value.count("present"),
            ),
        )
        cur.execute(
            """
            UPDATE matches
            SET status=%s, is_fun_mode=%s, solved_in_fun_mode=%s,
                last_activity_at=CURRENT_TIMESTAMP,
                completed_at=CASE
                    WHEN %s IN ('won', 'lost') AND NOT %s THEN CURRENT_TIMESTAMP
                    ELSE completed_at
                END
            WHERE matchid=%s AND userid=%s
            """,
            (
                new_status, is_fun_mode, solved_in_fun_mode, new_status,
                is_fun_mode, match_id, session["userid"],
            ),
        )
        result = {
            "guess": value.lower(),
            "feedback": feedback_value,
            "status": "fun" if exhausted else new_status,
            "attempt": turn,
        }
        if solved_in_fun_mode and won:
            result["fun_solved"] = True
            result["status"] = "lost"
        if won and not fun:
            result["ranking"] = ranking(cur, game_id, started, turn, match_id)
        return jsonify(result)


def ranking(cur, game_id, started, count, current_match_id):
    cur.execute(
        """
        SELECT m.started_at, m.completed_at, COUNT(mg.turn)
        FROM matches AS m
        LEFT JOIN match_guesses AS mg ON mg.matchid=m.matchid
        WHERE m.gameid=%s
          AND m.status='won'
          AND m.is_fun_mode=FALSE
          AND m.matchid<>%s
        GROUP BY m.matchid
        """,
        (game_id, current_match_id),
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
        cur.execute(
            """
            UPDATE matches
            SET status='lost', is_fun_mode=FALSE, answer_revealed=TRUE,
                completed_at=COALESCE(completed_at, CURRENT_TIMESTAMP),
                last_activity_at=CURRENT_TIMESTAMP
            WHERE matchid=%s AND userid=%s
            RETURNING gameid, status
            """,
            (match_id, session["userid"]),
        )
        row = cur.fetchone()
        if not row:
            return error("Match not found.", 404)
        cur.execute("SELECT gameword FROM games WHERE gameid=%s", (row[0],))
        secret = cur.fetchone()[0]
    return jsonify(secret=secret.lower(), status=row[1])


@app.get("/api/admin/reports/daily")
@admin_only
def daily_report():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT daily_date,
                   COUNT(DISTINCT userid),
                   COUNT(DISTINCT gameid),
                   SUM(CASE WHEN status='won' AND is_fun_mode=FALSE THEN 1 ELSE 0 END)
            FROM matches
            GROUP BY daily_date
            ORDER BY daily_date DESC
        """)
        return jsonify(report=[
            {
                "date": str(r[0]),
                "users": r[1],
                "words_tried": r[2] or 0,
                "correct_guesses": r[3] or 0,
            }
            for r in cur.fetchall()
        ])


@app.get("/api/admin/reports/words")
@admin_only
def word_report():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT g.gameword,
                   COUNT(m.matchid) AS matches,
                   SUM(CASE WHEN m.status='won' AND m.is_fun_mode=FALSE THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN m.status='lost' THEN 1 ELSE 0 END) AS losses,
                   MIN((
                       SELECT COUNT(*) FROM match_guesses AS mg
                       WHERE mg.matchid=m.matchid
                   )) FILTER (WHERE m.is_fun_mode=FALSE) AS min_guesses
            FROM games AS g
            LEFT JOIN matches AS m ON m.gameid=g.gameid
            GROUP BY g.gameword
            ORDER BY g.gameword
        """)
        return jsonify(report=[
            {
                "word": r[0],
                "matches": r[1],
                "wins": r[2] or 0,
                "losses": r[3] or 0,
                "min_guesses": r[4] or 0,
                "win_rate": round((r[2] or 0) * 100 / r[1], 2) if r[1] else 0,
            }
            for r in cur.fetchall()
        ])


@app.get("/api/admin/reports/users")
@admin_only
def user_report():
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.userid, u.username
            FROM userinfo AS u
            ORDER BY u.username
            """
        )
        return jsonify(
            report=[
                {
                    "userid": row[0],
                    "username": row[1],
                }
                for row in cur.fetchall()
            ]
        )


@app.get("/api/admin/reports/users/<int:userid>")
@admin_only
def user_detail_report(userid):
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.daily_date, g.gameword, m.status, m.is_fun_mode,
                   (SELECT COUNT(*) FROM match_guesses AS mg WHERE mg.matchid=m.matchid)
            FROM matches AS m
            JOIN games AS g ON g.gameid=m.gameid
            WHERE m.userid=%s
            ORDER BY m.daily_date DESC, m.started_at DESC
            """,
            (userid,),
        )
        rows = cur.fetchall()
    normal_matches = len(rows)
    normal_wins = sum(1 for row in rows if row[2] == "won" and not row[3])
    return jsonify(
        win_rate=round(normal_wins * 100 / normal_matches, 2) if normal_matches else 0,
        report=[
            {
                "date": str(row[0]),
                "question": row[1],
                "result": "win" if row[2] == "won" and not row[3] else "loss",
                "tries": row[4] or 0,
            }
            for row in rows
        ],
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
