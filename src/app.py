"""
Run Intel web dashboard — Flask backend.

Serves a React frontend and provides API endpoints for logging runs,
fetching Whoop data, and generating coaching insights.
"""

import hmac
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, make_response, redirect, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

# Add src/ to path so sibling modules resolve under gunicorn
sys.path.insert(0, str(Path(__file__).resolve().parent))

from briefing import generate_briefing
from config import APP_PASSWORD, FLASK_DEBUG, PORT, SESSION_SECRET
from database import Recovery, Run, get_session, init_db
from utils import (
    find_closest_run,
    format_pace,
    pace_str_to_seconds,
    safe_float,
    safe_int,
    seconds_to_pace,
    today_utc_start,
)
from whoop import WhoopClient

logger = logging.getLogger(__name__)

# ── Auth setup ────────────────────────────────────────────────────

_PASSWORD_HASH = generate_password_hash(APP_PASSWORD)
AUTH_TOKEN = hmac.new(SESSION_SECRET.encode(), APP_PASSWORD.encode(), "sha256").hexdigest()

app = Flask(__name__, static_folder="static")
app.secret_key = SESSION_SECRET

limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")

# Create tables on startup
init_db()


# ── Security headers ──────────────────────────────────────────────

@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not FLASK_DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ── Login page ────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Run Intel — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0A0A0A;color:#E0E0E0;font-family:'Outfit',sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh}
.login-card{background:#141414;border:1px solid #1E1E1E;border-radius:12px;
  padding:40px;width:100%;max-width:380px;text-align:center}
.bolt{font-size:32px;color:#00F19F}
h1{font-size:24px;font-weight:700;margin:12px 0 4px}
.subtitle{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#666;margin-bottom:28px}
input[type=password]{width:100%;background:#0A0A0A;border:1px solid #2A2A2A;border-radius:8px;
  padding:12px 14px;color:#E0E0E0;font-family:'JetBrains Mono',monospace;font-size:14px;
  outline:none;margin-bottom:16px;text-align:center;letter-spacing:2px}
input:focus{border-color:#00F19F}
button{width:100%;background:#00F19F;color:#0A0A0A;border:none;border-radius:8px;
  padding:12px;font-family:'Outfit',sans-serif;font-weight:600;font-size:14px;cursor:pointer}
button:hover{opacity:0.85}
.error{color:#FF4D4D;font-size:13px;margin-bottom:12px}
</style>
</head>
<body>
<div class="login-card">
  <div class="bolt">&#9889;</div>
  <h1>Run Intel</h1>
  <div class="subtitle">Powered by Whoop</div>
  {error}
  <form method="POST" action="/login">
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Enter</button>
  </form>
</div>
</body></html>"""


# ── Auth helpers ──────────────────────────────────────────────────

def require_auth(f):
    """Decorator: redirect to login if no valid auth cookie."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("auth_token", "")
        if not hmac.compare_digest(token, AUTH_TOKEN):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == "GET":
        token = request.cookies.get("auth_token", "")
        if hmac.compare_digest(token, AUTH_TOKEN):
            return redirect("/")
        return LOGIN_HTML.replace("{error}", "")
    # POST — check password
    password = request.form.get("password", "")
    if check_password_hash(_PASSWORD_HASH, password):
        resp = make_response(redirect("/"))
        resp.set_cookie(
            "auth_token", AUTH_TOKEN, max_age=60 * 60 * 24 * 30,
            httponly=True, samesite="Lax", secure=not FLASK_DEBUG,
        )
        return resp
    return LOGIN_HTML.replace("{error}", '<div class="error">Wrong password.</div>')


@app.route("/logout")
def logout():
    resp = make_response(redirect("/login"))
    resp.delete_cookie("auth_token")
    return resp


# ── Whoop recovery helper ────────────────────────────────────────

def fetch_and_cache_recovery(session) -> tuple[dict, str | None]:
    """Fetch today's recovery from Whoop, cache to DB.

    Returns (recovery_dict, date_iso) or ({defaults}, None) on failure.
    """
    today = date.today()
    defaults = {"recovery_score": None, "hrv": None, "resting_hr": None}

    # Try Whoop API first
    try:
        client = WhoopClient()
        recs = client.get_recovery(start=today_utc_start())
        if recs:
            score = recs[-1].get("score", {})
            recovery = {
                "recovery_score": score.get("recovery_score"),
                "hrv": score.get("hrv_rmssd_milli"),
                "resting_hr": score.get("resting_heart_rate"),
            }
            if recovery["recovery_score"] is not None:
                # Upsert to DB
                existing = session.query(Recovery).filter(Recovery.date == today).first()
                if existing:
                    existing.recovery_score = recovery["recovery_score"]
                    existing.hrv = recovery["hrv"]
                    existing.resting_hr = recovery["resting_hr"]
                else:
                    session.add(Recovery(date=today, **recovery))
                session.flush()
                return recovery, today.isoformat()
    except Exception:
        logger.exception("Error fetching recovery from Whoop")

    # Fall back to DB
    rec = session.query(Recovery).filter(Recovery.date == today).first()
    if rec and rec.recovery_score is not None:
        return {
            "recovery_score": rec.recovery_score,
            "hrv": rec.hrv,
            "resting_hr": rec.resting_hr,
        }, today.isoformat()

    # Fall back to most recent
    latest = (
        session.query(Recovery)
        .filter(Recovery.recovery_score.isnot(None))
        .order_by(Recovery.date.desc())
        .first()
    )
    if latest:
        return {
            "recovery_score": latest.recovery_score,
            "hrv": latest.hrv,
            "resting_hr": latest.resting_hr,
        }, latest.date.isoformat()

    return defaults, None


# ── Coaching insight ──────────────────────────────────────────────

def generate_coaching_insight(row: dict, recovery_data: dict | None) -> str:
    """Generate coaching insight based on recent run history."""
    today_pace_sec = pace_str_to_seconds(row.get("pace_per_mile"))
    today_hr = safe_float(row.get("avg_hr"))
    today_date = row.get("date")

    # Recovery context
    rec_score = safe_float(recovery_data.get("recovery_score")) if recovery_data else None
    rec_rhr = safe_float(recovery_data.get("resting_heart_rate")) if recovery_data else None
    rec_hrv = safe_float(recovery_data.get("hrv_rmssd_milli")) if recovery_data else None

    recovery_line = ""
    if rec_score is not None:
        color = "green" if rec_score >= 67 else ("yellow" if rec_score >= 34 else "red")
        parts = [f"Recovery: {rec_score:.0f}% ({color})"]
        if rec_rhr is not None:
            parts.append(f"RHR: {rec_rhr:.0f} bpm")
        if rec_hrv is not None:
            parts.append(f"HRV: {rec_hrv:.1f} ms")
        recovery_line = ". ".join(parts) + "."

    if today_pace_sec is None or today_hr is None:
        insight = "Run logged! Add more data points for coaching insights."
        if recovery_line:
            insight += f" {recovery_line}"
        return insight

    pace_display = seconds_to_pace(today_pace_sec)

    # Query only recent runs with valid data (not all runs)
    cutoff = date.fromisoformat(today_date) - timedelta(days=30) if today_date else date.today() - timedelta(days=30)

    with get_session() as session:
        runs = (
            session.query(Run)
            .filter(
                Run.date >= cutoff,
                Run.date < date.fromisoformat(today_date) if today_date else date.today(),
                Run.pace_per_mile.isnot(None),
                Run.avg_hr.isnot(None),
            )
            .all()
        )

    if not runs:
        insight = f"Building your baseline at {pace_display}/mi. Log a few more runs and I'll start giving pace recommendations."
        if recovery_line:
            insight += f" {recovery_line}"
        return insight

    # Find similar-pace runs (within 30 sec/mi)
    similar_hrs = []
    for r in runs:
        r_pace = pace_str_to_seconds(r.pace_per_mile)
        if r_pace and abs(r_pace - today_pace_sec) <= 30:
            similar_hrs.append(r.avg_hr)

    if len(similar_hrs) >= 3:
        avg_similar_hr = sum(similar_hrs) / len(similar_hrs)
        hr_diff = today_hr - avg_similar_hr

        if hr_diff < -3:
            faster_pace = seconds_to_pace(today_pace_sec - 10)
            insight = (
                f"Your avg HR at {pace_display}/mi has dropped from "
                f"{avg_similar_hr:.0f} to {today_hr:.0f} bpm. "
                f"Your body has adapted. Try {faster_pace}/mi next run."
            )
        elif hr_diff > 3 and rec_score is not None and rec_score < 50:
            insight = (
                f"HR was {hr_diff:.0f} bpm higher than usual at this pace. "
                f"Recovery was only {rec_score:.0f}% -- your body needs rest. "
                f"Don't push pace tomorrow."
            )
        elif hr_diff > 3:
            insight = (
                "HR was a bit elevated today. Could be heat, caffeine, or sleep. "
                "Nothing to worry about."
            )
        else:
            insight = (
                f"Solid run. You're consistent at {pace_display}/mi. "
                f"Keep building here."
            )
    else:
        insight = (
            f"Building your baseline at {pace_display}/mi. "
            f"Log a few more runs and I'll start giving pace recommendations."
        )

    if recovery_line:
        insight += f" {recovery_line}"
    return insight


# ── Routes ────────────────────────────────────────────────────────

@app.route("/")
@require_auth
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/briefing", methods=["GET"])
@require_auth
def get_briefing():
    """Return the morning briefing based on recovery, HRV, and strain data."""
    today = date.today()
    cutoff_30d = today - timedelta(days=30)

    with get_session() as session:
        today_recovery, recovery_date = fetch_and_cache_recovery(session)

        note = None
        if recovery_date and recovery_date != today.isoformat():
            note = "Recovery not yet scored today. Showing most recent data."

        recovery_rows = (
            session.query(Recovery)
            .filter(Recovery.date >= cutoff_30d, Recovery.date <= today)
            .order_by(Recovery.date)
            .all()
        )
        recovery_history = [r.to_dict() for r in recovery_rows]

        run_rows = (
            session.query(Run)
            .filter(Run.date >= cutoff_30d, Run.date <= today)
            .order_by(Run.date)
            .all()
        )
        run_history = [{"date": r.date.isoformat(), "strain": r.strain} for r in run_rows]

    result = generate_briefing(today_recovery, recovery_history, run_history)
    if result is None:
        return jsonify({"status": "unavailable", "status_label": "No recovery data available yet."})
    result["recovery_date"] = recovery_date
    if note:
        result["note"] = note
    return jsonify(result)


@app.route("/api/runs", methods=["GET"])
@require_auth
def get_runs():
    """Return all runs as JSON, newest first, with recovery scores."""
    with get_session() as session:
        results = (
            session.query(Run, Recovery.recovery_score)
            .outerjoin(Recovery, Run.date == Recovery.date)
            .order_by(Run.date.desc())
            .all()
        )
        records = []
        for run, recovery_score in results:
            d = run.to_dict()
            d["recovery_score"] = recovery_score
            records.append(d)
    return jsonify(records)


@app.route("/api/recovery/today", methods=["GET"])
@require_auth
def get_recovery_today():
    """Return today's recovery, fetching from Whoop if not cached."""
    with get_session() as session:
        recovery, recovery_date = fetch_and_cache_recovery(session)
    return jsonify({"date": recovery_date or date.today().isoformat(), **recovery})


@app.route("/api/shoes", methods=["GET"])
@require_auth
def get_shoes():
    """Sum miles per shoe from runs that have a shoe value."""
    with get_session() as session:
        results = (
            session.query(Run.shoes, func.sum(Run.distance_miles))
            .filter(Run.shoes.isnot(None), Run.shoes != "")
            .group_by(Run.shoes)
            .all()
        )
        shoes = [{"name": name, "miles": round(miles, 1)} for name, miles in results if miles]
        shoes.sort(key=lambda x: x["miles"], reverse=True)
    return jsonify(shoes)


@app.route("/api/trends", methods=["GET"])
@require_auth
def get_trends():
    """Return date, pace_seconds, avg_hr for runs with valid pace data."""
    with get_session() as session:
        runs = (
            session.query(Run)
            .filter(Run.pace_per_mile.isnot(None), Run.avg_hr.isnot(None))
            .order_by(Run.date)
            .all()
        )
        result = []
        for r in runs:
            pace_sec = pace_str_to_seconds(r.pace_per_mile)
            if pace_sec and 0 < pace_sec < 900:
                result.append({
                    "date": r.date.isoformat(),
                    "pace_seconds": pace_sec,
                    "avg_hr": r.avg_hr,
                })
    return jsonify(result)


@app.route("/api/snapshot", methods=["GET"])
@require_auth
def get_snapshot():
    """Return last 7d vs last 30d averages using SQL aggregates."""
    today = date.today()
    d7 = today - timedelta(days=7)
    d30 = today - timedelta(days=30)

    with get_session() as session:
        def run_avgs(since):
            row = session.query(
                func.avg(Run.avg_hr),
                func.avg(Run.strain),
            ).filter(Run.date >= since).first()
            return {"avg_hr": round(row[0], 1) if row[0] else None,
                    "avg_strain": round(row[1], 1) if row[1] else None}

        def rec_avgs(since):
            row = session.query(
                func.avg(Recovery.recovery_score),
                func.avg(Recovery.hrv),
                func.avg(Recovery.resting_hr),
            ).filter(Recovery.date >= since).first()
            return {"recovery": round(row[0], 1) if row[0] else None,
                    "hrv": round(row[1], 1) if row[1] else None,
                    "resting_hr": round(row[2], 1) if row[2] else None}

        r7, r30 = run_avgs(d7), run_avgs(d30)
        c7, c30 = rec_avgs(d7), rec_avgs(d30)

    return jsonify({
        "last_7d": {**r7, **c7},
        "last_30d": {**r30, **c30},
    })


@app.route("/api/runs", methods=["POST"])
@require_auth
def log_run():
    """Log a run: fetch Whoop data, generate coaching insight, save to DB."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request must be JSON"}), 400

    # Validate required fields
    raw_distance = data.get("distance_miles")
    raw_time = data.get("time_minutes")
    if raw_distance is None or raw_time is None:
        return jsonify({"error": "distance_miles and time_minutes are required"}), 400
    try:
        distance = float(raw_distance)
        time_min = float(raw_time)
    except (ValueError, TypeError):
        return jsonify({"error": "distance_miles and time_minutes must be numbers"}), 400
    if distance <= 0 or distance > 200:
        return jsonify({"error": "distance_miles must be between 0 and 200"}), 400
    if time_min <= 0 or time_min > 2000:
        return jsonify({"error": "time_minutes must be between 0 and 2000"}), 400

    shoe = data.get("shoe", "").lower().strip()
    pace = format_pace(time_min, distance)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Fetch today's Whoop workout
    client = WhoopClient()
    start = today_utc_start()

    workout = None
    recovery_data = None
    try:
        workouts = client.get_workouts(start=start)
        workout = find_closest_run(workouts)
    except Exception:
        logger.exception("Error fetching workouts from Whoop")
    try:
        recs = client.get_recovery(start=start)
        if recs:
            recovery_data = recs[-1].get("score", {})
    except Exception:
        logger.exception("Error fetching recovery from Whoop")

    # Build row dict
    row = {
        "date": today_str,
        "distance_miles": distance,
        "time_minutes": time_min,
        "pace_per_mile": pace,
        "avg_hr": None, "max_hr": None, "strain": None,
        "whoop_distance_meters": None,
        "zone_zero_milli": None, "zone_one_milli": None,
        "zone_two_milli": None, "zone_three_milli": None,
        "zone_four_milli": None, "zone_five_milli": None,
        "shoes": shoe,
    }
    if workout:
        score = workout.get("score", {})
        zones = score.get("zone_durations", {})
        row.update({
            "avg_hr": score.get("average_heart_rate"),
            "max_hr": score.get("max_heart_rate"),
            "strain": score.get("strain"),
            "whoop_distance_meters": score.get("distance_meter"),
            "zone_zero_milli": zones.get("zone_zero_milli"),
            "zone_one_milli": zones.get("zone_one_milli"),
            "zone_two_milli": zones.get("zone_two_milli"),
            "zone_three_milli": zones.get("zone_three_milli"),
            "zone_four_milli": zones.get("zone_four_milli"),
            "zone_five_milli": zones.get("zone_five_milli"),
        })

    # Save to database
    with get_session() as session:
        run = Run(
            date=date.fromisoformat(today_str),
            distance_miles=row["distance_miles"],
            time_minutes=row["time_minutes"],
            pace_per_mile=row["pace_per_mile"],
            avg_hr=safe_int(row["avg_hr"]),
            max_hr=safe_int(row["max_hr"]),
            strain=safe_float(row["strain"]),
            whoop_distance_meters=safe_float(row["whoop_distance_meters"]),
            zone_zero_milli=safe_int(row["zone_zero_milli"]),
            zone_one_milli=safe_int(row["zone_one_milli"]),
            zone_two_milli=safe_int(row["zone_two_milli"]),
            zone_three_milli=safe_int(row["zone_three_milli"]),
            zone_four_milli=safe_int(row["zone_four_milli"]),
            zone_five_milli=safe_int(row["zone_five_milli"]),
            shoes=row["shoes"],
        )
        session.add(run)

    # Generate coaching insight
    insight = generate_coaching_insight(row, recovery_data)

    return jsonify({"run": row, "coaching_insight": insight})


# ── Error handler ─────────────────────────────────────────────────

@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled exception")
    return jsonify({"error": "Internal server error"}), 500


# ── Startup ───────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Run Intel Dashboard: http://localhost:%d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=FLASK_DEBUG)
