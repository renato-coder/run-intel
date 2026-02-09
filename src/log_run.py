"""
Log a run with manual distance/time and matched Whoop workout data.

Usage:
    python src/log_run.py <distance_miles> <time_minutes> [shoe]

Shoes: alphafly, evosl, cloudmonster, zoomfly (optional)

Example:
    python src/log_run.py 6.2 48.5 alphafly
"""

import sys
import csv
from datetime import datetime, timezone
from pathlib import Path

from whoop import WhoopClient

VALID_SHOES = ["alphafly", "evosl", "cloudmonster", "zoomfly"]
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "runs.csv"

COLUMNS = [
    "date",
    "distance_miles",
    "time_minutes",
    "pace_per_mile",
    "avg_hr",
    "max_hr",
    "strain",
    "whoop_distance_meters",
    "zone_zero_milli",
    "zone_one_milli",
    "zone_two_milli",
    "zone_three_milli",
    "zone_four_milli",
    "zone_five_milli",
    "shoes",
]


def format_pace(total_minutes, distance_miles):
    """Convert total time and distance into pace string (e.g. '7:49')."""
    if distance_miles <= 0:
        return "N/A"
    pace_minutes = total_minutes / distance_miles
    mins = int(pace_minutes)
    secs = int((pace_minutes - mins) * 60)
    return f"{mins}:{secs:02d}"


def find_closest_run(workouts):
    """
    From today's workouts, find the running workout closest to the current time.
    Returns the workout dict or None.
    """
    now = datetime.now(timezone.utc)
    running = [w for w in workouts if w.get("sport_name", "").lower() == "running"]

    if not running:
        return None

    # Pick the one whose end time is closest to now
    def time_diff(w):
        end = w.get("end")
        if not end:
            return float("inf")
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return abs((now - end_dt).total_seconds())

    return min(running, key=time_diff)


def main():
    # ── Parse arguments ───────────────────────────────────────────────
    if len(sys.argv) < 3:
        print("Usage: python src/log_run.py <distance_miles> <time_minutes> [shoe]")
        sys.exit(1)

    distance_miles = float(sys.argv[1])
    time_minutes = float(sys.argv[2])
    shoe = sys.argv[3].lower() if len(sys.argv) > 3 else ""

    if shoe and shoe not in VALID_SHOES:
        print(f"Warning: '{shoe}' not in known shoes: {VALID_SHOES}")

    pace = format_pace(time_minutes, distance_miles)
    today = datetime.now().strftime("%Y-%m-%d")

    # ── Fetch today's Whoop workout ───────────────────────────────────
    client = WhoopClient()
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    workouts = client.get_workouts(start=today_start)
    workout = find_closest_run(workouts)

    if workout:
        score = workout.get("score", {})
        zones = score.get("zone_durations", {})
        row = {
            "date": today,
            "distance_miles": distance_miles,
            "time_minutes": time_minutes,
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
        print(f"Matched Whoop workout: strain {row['strain']}, avg HR {row['avg_hr']}")
    else:
        print("Warning: No running workout found on Whoop today. Logging without HR data.")
        row = {
            "date": today,
            "distance_miles": distance_miles,
            "time_minutes": time_minutes,
            "pace_per_mile": pace,
            "avg_hr": "",
            "max_hr": "",
            "strain": "",
            "whoop_distance_meters": "",
            "zone_zero_milli": "",
            "zone_one_milli": "",
            "zone_two_milli": "",
            "zone_three_milli": "",
            "zone_four_milli": "",
            "zone_five_milli": "",
            "shoes": shoe,
        }

    # ── Append to CSV ─────────────────────────────────────────────────
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = CSV_PATH.exists()

    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    print(f"Logged: {distance_miles} mi in {time_minutes} min ({pace}/mi) on {today}")


if __name__ == "__main__":
    main()
