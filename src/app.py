"""
Run Intel web dashboard — Flask backend.

Serves a React frontend and provides API endpoints for logging runs,
fetching Whoop data, and generating coaching insights.

Usage:
    python src/app.py
"""

import hmac
import os
import secrets
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, make_response, redirect, request, send_from_directory
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

# Add src/ to path so we can import whoop
sys.path.insert(0, str(Path(__file__).resolve().parent))
from briefing import generate_briefing
from database import Recovery, Run, SessionLocal, init_db
from whoop import WhoopClient

APP_PASSWORD = os.environ.get("APP_PASSWORD", "runintel2026")
# Pre-hash for password verification (scrypt with salt)
_PASSWORD_HASH = generate_password_hash(APP_PASSWORD)
# HMAC-based session token using the app secret
_SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))
AUTH_TOKEN = hmac.new(_SESSION_SECRET.encode(), APP_PASSWORD.encode(), "sha256").hexdigest()

app = Flask(__name__, static_folder="static")
app.secret_key = secrets.token_hex(32)

# Create tables on startup
init_db()

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
def login():
    if request.method == "GET":
        token = request.cookies.get("auth_token", "")
        if hmac.compare_digest(token, AUTH_TOKEN):
            return redirect("/")
        return LOGIN_HTML.replace("{error}", "")
    # POST — check password against scrypt hash
    password = request.form.get("password", "")
    if check_password_hash(_PASSWORD_HASH, password):
        resp = make_response(redirect("/"))
        resp.set_cookie("auth_token", AUTH_TOKEN, max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite="Lax", secure=True)
        return resp
    return LOGIN_HTML.replace("{error}", '<div class="error">Wrong password.</div>')


@app.route("/logout")
def logout():
    resp = make_response(redirect("/login"))
    resp.delete_cookie("auth_token")
    return resp


# ── Helpers ───────────────────────────────────────────────────────

def pace_str_to_seconds(pace_str):
    """Convert '7:49' to 469 seconds."""
    if not pace_str or not isinstance(pace_str, str) or ":" not in pace_str:
        return None
    parts = pace_str.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


def seconds_to_pace(secs):
    """Convert 469 seconds to '7:49'."""
    if secs is None or secs <= 0:
        return "N/A"
    m = int(secs) // 60
    s = int(secs) % 60
    return f"{m}:{s:02d}"


def format_pace(total_minutes, distance_miles):
    """Convert total time and distance into pace string."""
    if distance_miles <= 0:
        return "N/A"
    pace_minutes = total_minutes / distance_miles
    mins = int(pace_minutes)
    secs = int((pace_minutes - mins) * 60)
    return f"{mins}:{secs:02d}"


def find_closest_run(workouts):
    """Find the running workout closest to current time."""
    now = datetime.now(timezone.utc)
    running = [w for w in workouts if w.get("sport_name", "").lower() == "running"]
    if not running:
        return None

    def time_diff(w):
        end = w.get("end")
        if not end:
            return float("inf")
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return abs((now - end_dt).total_seconds())

    return min(running, key=time_diff)


def safe_float(val):
    """Convert to float, return None if not possible."""
    try:
        v = float(val)
        return v if pd.notna(v) else None
    except (ValueError, TypeError):
        return None


def safe_int(val):
    """Convert to int, return None if empty or invalid."""
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def generate_coaching_insight(row, recovery_data):
    """Generate coaching insight based on recent run history."""
    today_pace_sec = pace_str_to_seconds(row.get("pace_per_mile"))
    today_hr = safe_float(row.get("avg_hr"))
    today = row.get("date")

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

    # Need valid pace and HR
    if today_pace_sec is None or today_hr is None:
        insight = "Run logged! Add more data points for coaching insights."
        if recovery_line:
            insight += f" {recovery_line}"
        return insight

    pace_display = seconds_to_pace(today_pace_sec)

    # Find similar-pace runs from last 30 days
    session = SessionLocal()
    try:
        runs = session.query(Run).all()
    finally:
        session.close()

    if not runs:
        insight = f"Building your baseline at {pace_display}/mi. Log a few more runs and I'll start giving pace recommendations."
        if recovery_line:
            insight += f" {recovery_line}"
        return insight

    # Build a DataFrame from DB rows for the coaching logic
    run_dicts = [r.to_dict() for r in runs]
    df = pd.DataFrame(run_dicts)
    df["date"] = pd.to_datetime(df["date"])
    df["pace_sec"] = df["pace_per_mile"].apply(pace_str_to_seconds)
    df = df.dropna(subset=["pace_sec", "avg_hr"])
    df["avg_hr"] = pd.to_numeric(df["avg_hr"], errors="coerce")
    df = df.dropna(subset=["avg_hr"])

    # Last 30 days, similar pace (within 30 sec/mi), exclude today
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=30)
    similar = df[
        (df["date"] >= cutoff)
        & (df["date"] < pd.Timestamp(today))
        & ((df["pace_sec"] - today_pace_sec).abs() <= 30)
    ]

    if len(similar) >= 3:
        avg_similar_hr = similar["avg_hr"].mean()
        hr_diff = today_hr - avg_similar_hr

        if hr_diff < -3:
            # HR dropped — fitness improving
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

    today_recovery = {"recovery_score": None, "hrv": None, "resting_hr": None}
    recovery_date = None
    note = None

    session = SessionLocal()
    try:
        # Always try Whoop API first for freshest data
        whoop_fetched = False
        try:
            client = WhoopClient()
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            recs = client.get_recovery(start=today_start)
            if recs:
                score = recs[-1].get("score", {})
                today_recovery = {
                    "recovery_score": score.get("recovery_score"),
                    "hrv": score.get("hrv_rmssd_milli"),
                    "resting_hr": score.get("resting_heart_rate"),
                }
                if today_recovery["recovery_score"] is not None:
                    whoop_fetched = True
                    recovery_date = today.isoformat()
                    # Cache to DB (upsert)
                    existing = session.query(Recovery).filter(Recovery.date == today).first()
                    if existing:
                        existing.recovery_score = today_recovery["recovery_score"]
                        existing.hrv = today_recovery["hrv"]
                        existing.resting_hr = today_recovery["resting_hr"]
                    else:
                        session.add(Recovery(
                            date=today,
                            recovery_score=today_recovery["recovery_score"],
                            hrv=today_recovery["hrv"],
                            resting_hr=today_recovery["resting_hr"],
                        ))
                    session.commit()
        except Exception as e:
            print(f"Error fetching recovery from Whoop: {e}")

        # Fall back to DB if Whoop didn't return data
        if not whoop_fetched:
            # Try today's cached record first
            rec = session.query(Recovery).filter(Recovery.date == today).first()
            if rec and rec.recovery_score is not None:
                today_recovery = {
                    "recovery_score": rec.recovery_score,
                    "hrv": rec.hrv,
                    "resting_hr": rec.resting_hr,
                }
                recovery_date = today.isoformat()
            else:
                # Fall back to most recent recovery
                latest = (
                    session.query(Recovery)
                    .filter(Recovery.recovery_score.isnot(None))
                    .order_by(Recovery.date.desc())
                    .first()
                )
                if latest:
                    today_recovery = {
                        "recovery_score": latest.recovery_score,
                        "hrv": latest.hrv,
                        "resting_hr": latest.resting_hr,
                    }
                    recovery_date = latest.date.isoformat()
                    note = "Recovery not yet scored today. Showing most recent data."

        # Last 30 days of recovery
        recovery_rows = (
            session.query(Recovery)
            .filter(Recovery.date >= cutoff_30d, Recovery.date <= today)
            .order_by(Recovery.date)
            .all()
        )
        recovery_history = [r.to_dict() for r in recovery_rows]

        # Last 30 days of runs (for strain)
        run_rows = (
            session.query(Run)
            .filter(Run.date >= cutoff_30d, Run.date <= today)
            .order_by(Run.date)
            .all()
        )
        run_history = [{"date": r.date.isoformat(), "strain": r.strain} for r in run_rows]
    finally:
        session.close()

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
    session = SessionLocal()
    try:
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
    finally:
        session.close()


@app.route("/api/recovery/today", methods=["GET"])
@require_auth
def get_recovery_today():
    """Return today's recovery, fetching from Whoop if not cached."""
    today = date.today()

    session = SessionLocal()
    try:
        rec = session.query(Recovery).filter(Recovery.date == today).first()
        if rec:
            return jsonify(rec.to_dict())

        # Fetch from Whoop API
        try:
            client = WhoopClient()
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            recs = client.get_recovery(start=today_start)
            if recs:
                score = recs[-1].get("score", {})
                data = {
                    "recovery_score": score.get("recovery_score"),
                    "hrv": score.get("hrv_rmssd_milli"),
                    "resting_hr": score.get("resting_heart_rate"),
                }
                # Cache to DB
                if data["recovery_score"] is not None:
                    new_rec = Recovery(
                        date=today,
                        recovery_score=data["recovery_score"],
                        hrv=data["hrv"],
                        resting_hr=data["resting_hr"],
                    )
                    session.add(new_rec)
                    session.commit()
                return jsonify({"date": today.isoformat(), **data})
        except Exception as e:
            print(f"Error fetching recovery: {e}")
    finally:
        session.close()

    return jsonify({"date": today.isoformat(), "recovery_score": None, "hrv": None, "resting_hr": None})


@app.route("/api/shoes", methods=["GET"])
@require_auth
def get_shoes():
    """Sum miles per shoe from runs that have a shoe value."""
    session = SessionLocal()
    try:
        results = (
            session.query(Run.shoes, func.sum(Run.distance_miles))
            .filter(Run.shoes.isnot(None), Run.shoes != "")
            .group_by(Run.shoes)
            .all()
        )
        shoes = [{"name": name, "miles": round(miles, 1)} for name, miles in results if miles]
        shoes.sort(key=lambda x: x["miles"], reverse=True)
        return jsonify(shoes)
    finally:
        session.close()


@app.route("/api/trends", methods=["GET"])
@require_auth
def get_trends():
    """Return date, pace_seconds, avg_hr for runs with valid pace data."""
    session = SessionLocal()
    try:
        runs = (
            session.query(Run)
            .filter(Run.pace_per_mile.isnot(None), Run.avg_hr.isnot(None))
            .order_by(Run.date)
            .all()
        )
    finally:
        session.close()

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
    """Return last 7d vs last 30d averages."""
    session = SessionLocal()
    try:
        runs = session.query(Run).all()
        recoveries = session.query(Recovery).all()
    finally:
        session.close()

    if not runs:
        return jsonify({"last_7d": {}, "last_30d": {}})

    run_df = pd.DataFrame([r.to_dict() for r in runs])
    run_df["date"] = pd.to_datetime(run_df["date"])

    rec_df = pd.DataFrame([r.to_dict() for r in recoveries]) if recoveries else pd.DataFrame()
    if not rec_df.empty:
        rec_df["date"] = pd.to_datetime(rec_df["date"])

    now = run_df["date"].max()
    d7 = now - pd.Timedelta(days=7)
    d30 = now - pd.Timedelta(days=30)

    def avg_metrics(run_slice, rec_slice):
        result = {}
        hr = pd.to_numeric(run_slice["avg_hr"], errors="coerce").dropna()
        strain = pd.to_numeric(run_slice["strain"], errors="coerce").dropna()
        if not hr.empty:
            result["avg_hr"] = round(hr.mean(), 1)
        if not strain.empty:
            result["avg_strain"] = round(strain.mean(), 1)
        if rec_slice is not None and not rec_slice.empty:
            rec = rec_slice["recovery_score"].dropna()
            hrv = rec_slice["hrv"].dropna()
            rhr = rec_slice["resting_hr"].dropna()
            if not rec.empty:
                result["recovery"] = round(rec.mean(), 1)
            if not hrv.empty:
                result["hrv"] = round(hrv.mean(), 1)
            if not rhr.empty:
                result["resting_hr"] = round(rhr.mean(), 1)
        return result

    rec_7 = rec_df[rec_df["date"] >= d7] if not rec_df.empty else None
    rec_30 = rec_df[rec_df["date"] >= d30] if not rec_df.empty else None

    return jsonify({
        "last_7d": avg_metrics(run_df[run_df["date"] >= d7], rec_7),
        "last_30d": avg_metrics(run_df[run_df["date"] >= d30], rec_30),
    })


@app.route("/api/runs", methods=["POST"])
@require_auth
def log_run():
    """Log a run: fetch Whoop data, generate coaching insight, save to DB."""
    data = request.get_json()
    distance = float(data["distance_miles"])
    time_min = float(data["time_minutes"])
    shoe = data.get("shoe", "").lower().strip()

    pace = format_pace(time_min, distance)
    today = datetime.now().strftime("%Y-%m-%d")

    # Fetch today's Whoop workout
    client = WhoopClient()
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    workout = None
    recovery_data = None
    try:
        workouts = client.get_workouts(start=today_start)
        workout = find_closest_run(workouts)
    except Exception as e:
        print(f"Error fetching workouts: {e}")

    try:
        recs = client.get_recovery(start=today_start)
        if recs:
            recovery_data = recs[-1].get("score", {})
    except Exception as e:
        print(f"Error fetching recovery: {e}")

    # Build row dict (for coaching insight)
    if workout:
        score = workout.get("score", {})
        zones = score.get("zone_durations", {})
        row = {
            "date": today,
            "distance_miles": distance,
            "time_minutes": time_min,
            "pace_per_mile": pace,
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
            "shoes": shoe,
        }
    else:
        row = {
            "date": today,
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

    # Save to database
    run = Run(
        date=date.fromisoformat(today),
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
    session = SessionLocal()
    try:
        session.add(run)
        session.commit()
    finally:
        session.close()

    # Generate coaching insight
    insight = generate_coaching_insight(row, recovery_data)

    return jsonify({"run": row, "coaching_insight": insight})



# ── Background Recovery Refresh ──────────────────────────────────

REFRESH_INTERVAL = 30 * 60  # 30 minutes


def _refresh_recovery():
    """Fetch latest recovery from Whoop and store to DB."""
    try:
        client = WhoopClient()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        recs = client.get_recovery(start=today_start)
        if recs:
            score = recs[-1].get("score", {})
            recovery_score = score.get("recovery_score")
            hrv = score.get("hrv_rmssd_milli")
            resting_hr = score.get("resting_heart_rate")
            if recovery_score is not None:
                today = date.today()
                session = SessionLocal()
                try:
                    existing = session.query(Recovery).filter(Recovery.date == today).first()
                    if existing:
                        existing.recovery_score = recovery_score
                        existing.hrv = hrv
                        existing.resting_hr = resting_hr
                    else:
                        session.add(Recovery(
                            date=today,
                            recovery_score=recovery_score,
                            hrv=hrv,
                            resting_hr=resting_hr,
                        ))
                    session.commit()
                    print(f"[bg-refresh] Recovery updated: {recovery_score}%")
                finally:
                    session.close()
            else:
                print("[bg-refresh] Whoop returned no recovery score yet.")
        else:
            print("[bg-refresh] No recovery data from Whoop.")
    except Exception as e:
        print(f"[bg-refresh] Error: {e}")


def _schedule_refresh():
    """Run recovery refresh, then schedule the next one."""
    _refresh_recovery()
    t = threading.Timer(REFRESH_INTERVAL, _schedule_refresh)
    t.daemon = True
    t.start()


# Start background refresh on app load
_bg_thread = threading.Timer(5, _schedule_refresh)  # 5s delay to let app start
_bg_thread.daemon = True
_bg_thread.start()
print("[bg-refresh] Background recovery refresh scheduled (every 30 min).")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"\n  Run Intel Dashboard: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
