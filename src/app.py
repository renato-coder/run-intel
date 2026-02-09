"""
Run Intel web dashboard — Flask backend.

Serves a React frontend and provides API endpoints for logging runs,
fetching Whoop data, and generating coaching insights.

Usage:
    python src/app.py
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

# Add src/ to path so we can import whoop
sys.path.insert(0, str(Path(__file__).resolve().parent))
from whoop import WhoopClient

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUNS_CSV = DATA_DIR / "runs.csv"
RECOVERY_CSV = DATA_DIR / "recovery.csv"

COLUMNS = [
    "date", "distance_miles", "time_minutes", "pace_per_mile",
    "avg_hr", "max_hr", "strain", "whoop_distance_meters",
    "zone_zero_milli", "zone_one_milli", "zone_two_milli",
    "zone_three_milli", "zone_four_milli", "zone_five_milli", "shoes",
]

app = Flask(__name__, static_folder="static")


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


def load_runs():
    """Load runs.csv into a DataFrame."""
    if not RUNS_CSV.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(RUNS_CSV, parse_dates=["date"])


def load_recovery():
    """Load recovery.csv into a DataFrame."""
    if not RECOVERY_CSV.exists():
        return pd.DataFrame(columns=["date", "recovery_score", "hrv", "resting_hr"])
    return pd.read_csv(RECOVERY_CSV, parse_dates=["date"])


def safe_float(val):
    """Convert to float, return None if not possible."""
    try:
        v = float(val)
        return v if pd.notna(v) else None
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
    runs = load_runs()
    if runs.empty:
        insight = f"Building your baseline at {pace_display}/mi. Log a few more runs and I'll start giving pace recommendations."
        if recovery_line:
            insight += f" {recovery_line}"
        return insight

    runs["pace_sec"] = runs["pace_per_mile"].apply(pace_str_to_seconds)
    runs = runs.dropna(subset=["pace_sec", "avg_hr"])
    runs["avg_hr"] = pd.to_numeric(runs["avg_hr"], errors="coerce")
    runs = runs.dropna(subset=["avg_hr"])

    # Last 30 days, similar pace (within 30 sec/mi), exclude today
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=30)
    similar = runs[
        (runs["date"] >= cutoff)
        & (runs["date"] < pd.Timestamp(today))
        & ((runs["pace_sec"] - today_pace_sec).abs() <= 30)
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
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/runs", methods=["GET"])
def get_runs():
    """Return all runs as JSON, newest first."""
    runs = load_runs()
    runs = runs.sort_values("date", ascending=False)
    # Convert to records, handling NaN
    records = runs.where(runs.notna(), None).to_dict("records")
    # Format dates as strings
    for r in records:
        if r.get("date") and hasattr(r["date"], "strftime"):
            r["date"] = r["date"].strftime("%Y-%m-%d")
    return jsonify(records)


@app.route("/api/recovery/today", methods=["GET"])
def get_recovery_today():
    """Return today's recovery, fetching from Whoop if not cached."""
    today = datetime.now().strftime("%Y-%m-%d")
    recovery = load_recovery()

    # Check if today is in CSV
    if not recovery.empty:
        today_rec = recovery[recovery["date"].dt.strftime("%Y-%m-%d") == today]
        if not today_rec.empty:
            row = today_rec.iloc[-1]
            return jsonify({
                "date": today,
                "recovery_score": safe_float(row.get("recovery_score")),
                "hrv": safe_float(row.get("hrv")),
                "resting_hr": safe_float(row.get("resting_hr")),
            })

    # Fetch from Whoop API
    try:
        client = WhoopClient()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        recs = client.get_recovery(start=today_start)
        if recs:
            score = recs[-1].get("score", {})
            return jsonify({
                "date": today,
                "recovery_score": score.get("recovery_score"),
                "hrv": score.get("hrv_rmssd_milli"),
                "resting_hr": score.get("resting_heart_rate"),
            })
    except Exception as e:
        print(f"Error fetching recovery: {e}")

    return jsonify({"date": today, "recovery_score": None, "hrv": None, "resting_hr": None})


@app.route("/api/shoes", methods=["GET"])
def get_shoes():
    """Sum miles per shoe from runs that have a shoe value."""
    runs = load_runs()
    runs = runs[runs["shoes"].notna() & (runs["shoes"] != "")]
    if runs.empty:
        return jsonify([])

    runs["distance_miles"] = pd.to_numeric(runs["distance_miles"], errors="coerce")
    grouped = runs.groupby("shoes")["distance_miles"].sum().reset_index()
    result = [{"name": r["shoes"], "miles": round(r["distance_miles"], 1)}
              for _, r in grouped.iterrows()]
    result.sort(key=lambda x: x["miles"], reverse=True)
    return jsonify(result)


@app.route("/api/trends", methods=["GET"])
def get_trends():
    """Return date, pace_seconds, avg_hr for runs with valid pace data."""
    runs = load_runs()
    runs["pace_sec"] = runs["pace_per_mile"].apply(pace_str_to_seconds)
    runs["avg_hr"] = pd.to_numeric(runs["avg_hr"], errors="coerce")
    valid = runs.dropna(subset=["pace_sec", "avg_hr"]).copy()
    valid = valid[(valid["pace_sec"] > 0) & (valid["pace_sec"] < 900)]  # < 15 min/mi
    valid = valid.sort_values("date")

    result = []
    for _, r in valid.iterrows():
        d = r["date"]
        result.append({
            "date": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
            "pace_seconds": int(r["pace_sec"]),
            "avg_hr": round(r["avg_hr"]),
        })
    return jsonify(result)


@app.route("/api/snapshot", methods=["GET"])
def get_snapshot():
    """Return last 7d vs last 30d averages."""
    runs = load_runs()
    recovery = load_recovery()

    if runs.empty:
        return jsonify({"last_7d": {}, "last_30d": {}})

    now = runs["date"].max()
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

    rec_7 = recovery[recovery["date"] >= d7] if not recovery.empty else None
    rec_30 = recovery[recovery["date"] >= d30] if not recovery.empty else None

    return jsonify({
        "last_7d": avg_metrics(runs[runs["date"] >= d7], rec_7),
        "last_30d": avg_metrics(runs[runs["date"] >= d30], rec_30),
    })


@app.route("/api/runs", methods=["POST"])
def log_run():
    """Log a run: fetch Whoop data, generate coaching insight, save to CSV."""
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

    # Build row
    if workout:
        score = workout.get("score", {})
        zones = score.get("zone_durations", {})
        row = {
            "date": today,
            "distance_miles": distance,
            "time_minutes": time_min,
            "pace_per_mile": pace,
            "avg_hr": score.get("average_heart_rate", ""),
            "max_hr": score.get("max_heart_rate", ""),
            "strain": score.get("strain", ""),
            "whoop_distance_meters": score.get("distance_meter", ""),
            "zone_zero_milli": zones.get("zone_zero_milli", ""),
            "zone_one_milli": zones.get("zone_one_milli", ""),
            "zone_two_milli": zones.get("zone_two_milli", ""),
            "zone_three_milli": zones.get("zone_three_milli", ""),
            "zone_four_milli": zones.get("zone_four_milli", ""),
            "zone_five_milli": zones.get("zone_five_milli", ""),
            "shoes": shoe,
        }
    else:
        row = {
            "date": today,
            "distance_miles": distance,
            "time_minutes": time_min,
            "pace_per_mile": pace,
            "avg_hr": "", "max_hr": "", "strain": "",
            "whoop_distance_meters": "",
            "zone_zero_milli": "", "zone_one_milli": "",
            "zone_two_milli": "", "zone_three_milli": "",
            "zone_four_milli": "", "zone_five_milli": "",
            "shoes": shoe,
        }

    # Save to CSV
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = RUNS_CSV.exists()
    with open(RUNS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    # Generate coaching insight
    insight = generate_coaching_insight(row, recovery_data)

    return jsonify({"run": row, "coaching_insight": insight})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"\n  Run Intel Dashboard: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
