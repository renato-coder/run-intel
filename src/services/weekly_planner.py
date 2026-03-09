"""
Weekly training plan generator for Run Intel.

Pure computation — no database access. Takes metrics + profile data in,
returns a structured 7-day plan out.
"""

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from services.coaching import MetricsSnapshot, _secs_to_pace, compute_hr_zones, vdot_paces


@dataclass
class Segment:
    activity: str       # "run" | "warmup" | "cooldown" | "intervals" | "lift"
    description: str
    distance_miles: float | None = None
    pace: str | None = None
    pace_max: str | None = None
    hr_target: str | None = None
    duration_min: int | None = None
    reps: int | None = None
    recovery_min: int | None = None


@dataclass
class DayPlan:
    date: str
    day_label: str
    type: str           # "lift_easy" | "quality" | "volume" | "long" | "shakeout" | "rest"
    title: str
    segments: list
    notes: str
    recovery_adjustment: str | None
    total_miles: float


@dataclass
class WeeklyPlan:
    week_start: str
    weekly_miles_target: float
    days: list
    generation_context: str


# ── Lift schedule (default template) ────────────────────────────

LIFT_SCHEDULE = {
    0: "chest",   # Monday
    2: "legs",    # Wednesday
    4: "back",    # Friday
}


def generate_weekly_plan(
    metrics: MetricsSnapshot,
    profile_data: dict,
    latest_recovery: float | None,
    week_start: date,
) -> WeeklyPlan:
    """Generate a 7-day training plan from current fitness data.

    Args:
        metrics: Current MetricsSnapshot (VDOT, CTL, ATL, TSB, etc.)
        profile_data: Dict from UserProfile.to_dict()
        latest_recovery: Most recent Whoop recovery score (0-100)
        week_start: Monday of the target week
    """
    vdot = metrics.vdot
    ctl = metrics.ctl
    tsb = metrics.tsb
    acwr = metrics.acwr
    max_hr = profile_data.get("max_hr")
    age = profile_data.get("age")

    # Estimate max HR from age if not set
    if not max_hr and age:
        max_hr = int(208 - 0.7 * age)

    # Compute pace targets
    paces = vdot_paces(vdot)
    zones = compute_hr_zones(max_hr) if max_hr else {}

    easy_pace = _secs_to_pace(paces["easy"])
    easy_pace_max = _secs_to_pace(paces["easy"] + 30)
    marathon_pace = _secs_to_pace(paces["marathon"])
    marathon_pace_max = _secs_to_pace(paces["marathon"] + 15)
    tempo_pace = _secs_to_pace(paces["tempo"])
    tempo_pace_max = _secs_to_pace(paces["tempo"] + 15)
    interval_pace = _secs_to_pace(paces["interval"])
    interval_pace_max = _secs_to_pace(paces["interval"] + 15)

    easy_hr = zones.get("easy_cap", "")
    marathon_hr_low = zones.get("marathon_low", "")
    marathon_hr_high = zones.get("marathon_high", "")
    interval_hr_low = zones.get("interval_low", "")
    interval_hr_high = zones.get("interval_high", "")
    recovery_hr = zones.get("recovery", "")
    shakeout_hr = int(max_hr * 0.74) if max_hr else ""

    # Weekly mileage target from CTL
    if ctl and ctl > 5:
        base_miles = max(25, ctl * 1.2)
    else:
        base_miles = 30  # conservative default

    weekly_miles = min(round(base_miles, 0), 55)

    # Cutback week if heavily fatigued
    cutback = False
    if tsb is not None and tsb < -25:
        weekly_miles = round(weekly_miles * 0.7)
        cutback = True
    elif acwr is not None and acwr > 1.4:
        weekly_miles = round(weekly_miles * 0.8)
        cutback = True

    # Distribute miles
    long_run_miles = round(weekly_miles * 0.25, 1)
    quality_miles = round(weekly_miles * 0.15, 1)  # total for quality day incl. warmup/cooldown
    remaining = weekly_miles - long_run_miles - quality_miles
    # Split remaining across 4 easy-ish days (Mon, Wed, Fri, Sat) + Thu volume
    thu_miles = round(remaining * 0.35, 1)  # Thu gets more (volume day)
    easy_per_day = round((remaining - thu_miles) / 3, 1)  # Mon, Wed, Fri
    sat_miles = round(remaining - thu_miles - easy_per_day * 2, 1)  # Sat shakeout (lighter)
    # Ensure minimums
    easy_per_day = max(easy_per_day, 3)
    sat_miles = max(sat_miles, 3)

    # Determine quality session type
    # VO2 intervals when TSB is positive (fresh), tempo when building
    if tsb is not None and tsb > 0:
        quality_type = "vo2"
    else:
        quality_type = "tempo"

    days = []

    for day_offset in range(7):
        d = week_start + timedelta(days=day_offset)
        day_label = d.strftime("%A")
        dow = day_offset  # 0=Mon, 6=Sun

        if dow == 0:
            # Monday — Lift + Easy Run
            lift = LIFT_SCHEDULE.get(dow, "upper")
            mon_miles = min(easy_per_day, 3) if not cutback else 2
            days.append(_day_dict(d, day_label, "lift_easy",
                f"{lift.title()} + Easy Run",
                [
                    {"activity": "lift", "description": f"{lift.title()} day (45 min)", "duration_min": 45},
                    {"activity": "run", "description": f"{mon_miles} mi easy @ {easy_pace}-{easy_pace_max}",
                     "distance_miles": mon_miles, "pace": easy_pace, "pace_max": easy_pace_max,
                     "hr_target": f"< {easy_hr}" if easy_hr else None},
                ],
                mon_miles,
                "Shorter than usual after Sunday's long run. Save legs for tomorrow's quality session.",
                "If recovery < 40%, skip the run and just lift." if not cutback else "Cutback week — keep it easy.",
            ))

        elif dow == 1:
            # Tuesday — Quality Session #1
            if quality_type == "vo2":
                warmup = 1.5
                cooldown = 1.0
                interval_total = quality_miles - warmup - cooldown
                days.append(_day_dict(d, day_label, "quality",
                    "VO2 Max Intervals",
                    [
                        {"activity": "warmup", "description": f"{warmup} mi warmup @ {easy_pace}",
                         "distance_miles": warmup, "pace": easy_pace},
                        {"activity": "intervals",
                         "description": f"4x4 min @ {interval_pace}-{interval_pace_max}, 3 min jog recovery",
                         "reps": 4, "duration_min": 4, "pace": interval_pace, "pace_max": interval_pace_max,
                         "hr_target": f"{interval_hr_low}-{interval_hr_high}" if interval_hr_low else None,
                         "recovery_min": 3},
                        {"activity": "cooldown", "description": f"{cooldown} mi cooldown @ easy",
                         "distance_miles": cooldown, "pace": "easy"},
                    ],
                    quality_miles,
                    f"Recovery jogs: drop HR to {recovery_hr} before next rep." if recovery_hr else "Full recovery between reps.",
                    "If recovery < 50%, reduce to 3x4 min.",
                ))
            else:
                warmup = 1.5
                tempo_miles = round(quality_miles - 3, 1)
                if tempo_miles < 2:
                    tempo_miles = 2
                cooldown = 1.0
                days.append(_day_dict(d, day_label, "quality",
                    "Tempo Run",
                    [
                        {"activity": "warmup", "description": f"{warmup} mi warmup @ {easy_pace}",
                         "distance_miles": warmup, "pace": easy_pace},
                        {"activity": "run", "description": f"{tempo_miles} mi @ {tempo_pace}-{tempo_pace_max}",
                         "distance_miles": tempo_miles, "pace": tempo_pace, "pace_max": tempo_pace_max,
                         "hr_target": f"< {zones.get('tempo', '')}" if zones.get("tempo") else None},
                        {"activity": "cooldown", "description": f"{cooldown} mi cooldown @ easy",
                         "distance_miles": cooldown, "pace": "easy"},
                    ],
                    warmup + tempo_miles + cooldown,
                    "Tempo effort should feel 'comfortably hard' — you can speak in short phrases.",
                    "If recovery < 50%, convert to easy run at the same distance.",
                ))

        elif dow == 2:
            # Wednesday — Legs + Easy Run
            lift = LIFT_SCHEDULE.get(dow, "legs")
            wed_miles = easy_per_day
            days.append(_day_dict(d, day_label, "lift_easy",
                f"{lift.title()} + Easy Run",
                [
                    {"activity": "lift", "description": f"{lift.title()} day (45 min)", "duration_min": 45},
                    {"activity": "run", "description": f"{wed_miles} mi easy @ {easy_pace}",
                     "distance_miles": wed_miles, "pace": easy_pace, "pace_max": easy_pace_max,
                     "hr_target": f"< {easy_hr}" if easy_hr else None},
                ],
                wed_miles,
                "Post-VO2 day — legs will be heavy. Keep it truly easy.",
                "If patellar tendon is sore, reduce squat depth or swap to leg press.",
            ))

        elif dow == 3:
            # Thursday — Mid-Week Volume
            days.append(_day_dict(d, day_label, "volume",
                "Mid-Week Volume",
                [
                    {"activity": "run", "description": f"{thu_miles} mi easy @ {easy_pace}-{easy_pace_max}",
                     "distance_miles": thu_miles, "pace": easy_pace, "pace_max": easy_pace_max,
                     "hr_target": f"< {easy_hr}" if easy_hr else None},
                    {"activity": "strides", "description": "6x20 sec strides with full recovery",
                     "reps": 6, "duration_min": 0},
                ],
                thu_miles,
                "No lifting. Strides on flat ground at end of run. Brief burst, full recovery between each.",
                None,
            ))

        elif dow == 4:
            # Friday — Back + Easy Run
            lift = LIFT_SCHEDULE.get(dow, "back")
            fri_miles = easy_per_day
            days.append(_day_dict(d, day_label, "lift_easy",
                f"{lift.title()} + Easy Run",
                [
                    {"activity": "lift", "description": f"{lift.title()} day (45 min)", "duration_min": 45},
                    {"activity": "run", "description": f"{fri_miles} mi easy @ {easy_pace}",
                     "distance_miles": fri_miles, "pace": easy_pace, "pace_max": easy_pace_max,
                     "hr_target": f"< {easy_hr}" if easy_hr else None},
                ],
                fri_miles,
                f"{lift.title()} day won't tax legs — run should feel smooth.",
                None,
            ))

        elif dow == 5:
            # Saturday — Pre-Long-Run Shakeout
            days.append(_day_dict(d, day_label, "shakeout",
                "Pre-Long-Run Shakeout",
                [
                    {"activity": "run", "description": f"{sat_miles} mi easy @ {easy_pace}",
                     "distance_miles": sat_miles, "pace": easy_pace, "pace_max": easy_pace_max,
                     "hr_target": f"< {shakeout_hr}" if shakeout_hr else None},
                ],
                sat_miles,
                "No lifting. No intensity. No strides. Hydrate well. Eat carbs at dinner.",
                None,
            ))

        elif dow == 6:
            # Sunday — Long Run
            easy_portion = round(long_run_miles * 0.75, 1)
            mp_portion = round(long_run_miles - easy_portion, 1)
            days.append(_day_dict(d, day_label, "long",
                "Long Run",
                [
                    {"activity": "run",
                     "description": f"{easy_portion} mi easy @ {easy_pace}-{_secs_to_pace(paces['easy'] + 15)}",
                     "distance_miles": easy_portion, "pace": easy_pace,
                     "hr_target": f"< {easy_hr}" if easy_hr else None},
                    {"activity": "run",
                     "description": f"Last {mp_portion} mi @ marathon pace {marathon_pace}-{marathon_pace_max}",
                     "distance_miles": mp_portion, "pace": marathon_pace, "pace_max": marathon_pace_max,
                     "hr_target": f"{marathon_hr_low}-{marathon_hr_high}" if marathon_hr_low else None},
                ],
                long_run_miles,
                f"Fuel after mile 8 if needed. Total: {long_run_miles} miles.",
                "If recovery < 50%, run all easy — skip the marathon pace finish.",
            ))

    context_parts = []
    if vdot:
        context_parts.append(f"VDOT {vdot}")
    if ctl:
        context_parts.append(f"CTL {ctl}")
    if latest_recovery is not None:
        context_parts.append(f"Recovery {latest_recovery:.0f}%")
    if cutback:
        context_parts.append("CUTBACK WEEK")
    context = "Based on " + ", ".join(context_parts) if context_parts else "Default plan (insufficient data)"

    return WeeklyPlan(
        week_start=week_start.isoformat(),
        weekly_miles_target=weekly_miles,
        days=days,
        generation_context=context,
    )


def _day_dict(d: date, day_label: str, day_type: str, title: str,
              segments: list, total_miles: float, notes: str,
              recovery_adjustment: str | None) -> dict:
    """Build a day plan dict."""
    return {
        "date": d.isoformat(),
        "day_label": day_label,
        "type": day_type,
        "title": title,
        "segments": segments,
        "notes": notes,
        "recovery_adjustment": recovery_adjustment,
        "total_miles": total_miles,
    }
