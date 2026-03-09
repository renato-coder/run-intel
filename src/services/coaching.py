"""
Pure computation functions for coaching metrics.

No database access — all functions take data in, return results out.
"""

from dataclasses import dataclass
from datetime import date
import math


@dataclass
class WorkoutRx:
    type: str          # "easy" | "tempo" | "intervals" | "long" | "rest"
    distance_miles: float
    pace_min: str      # "8:10"
    pace_max: str      # "8:30"
    hr_cap: int | None
    description: str
    rationale: str


@dataclass
class MetricsSnapshot:
    ef_30d: float | None
    ef_90d: float | None
    ef_trend: str | None      # "improving" | "plateau" | "declining"
    vdot: float | None
    ctl: float | None
    atl: float | None
    tsb: float | None
    acwr: float | None
    estimated_vo2max: float | None
    zone2_minutes_week: int | None


def _secs_to_pace(secs: float) -> str:
    """Convert seconds to pace string like '8:15'."""
    if secs <= 0:
        return "N/A"
    m = int(secs) // 60
    s = int(secs) % 60
    return f"{m}:{s:02d}"


def compute_efficiency_factor(pace_seconds_per_mile: float, avg_hr: float) -> float | None:
    """EF = yards per heartbeat. Higher = more efficient."""
    if not pace_seconds_per_mile or not avg_hr or pace_seconds_per_mile <= 0 or avg_hr <= 0:
        return None
    yards_per_mile = 1760
    yards_per_minute = (yards_per_mile / pace_seconds_per_mile) * 60
    return round(yards_per_minute / avg_hr, 2)


def estimate_vdot(distance_miles: float, time_minutes: float) -> float | None:
    """Estimate VDOT from a race/time-trial performance.

    Uses simplified linear fit from Daniels' tables for marathon-range distances.
    """
    if not distance_miles or not time_minutes or distance_miles <= 0 or time_minutes <= 0:
        return None
    pace_per_mile = time_minutes / distance_miles
    pace_seconds = pace_per_mile * 60
    # Linear fit: sub-3 marathon (6:52/mi=412s) => VDOT 54
    #             3:30 marathon (8:00/mi=480s) => VDOT 45
    # slope: (54-45)/(480-412) = 9/68 ≈ -0.132 per second
    vdot = 97.0 - (0.1 * pace_seconds)
    return max(30, min(85, round(vdot, 1)))


def compute_tss(duration_minutes: float, avg_hr: float, threshold_hr: float) -> float | None:
    """Training Stress Score = duration * (intensity_factor)^2."""
    if not all([duration_minutes, avg_hr, threshold_hr]) or threshold_hr <= 0:
        return None
    intensity_factor = avg_hr / threshold_hr
    return round(duration_minutes * intensity_factor * intensity_factor, 1)


def compute_training_load(daily_tss: list[float], acute_window: int = 7, chronic_window: int = 42) -> tuple[float | None, float | None, float | None]:
    """Compute CTL, ATL, TSB from a list of daily TSS values (oldest first).

    Returns (ctl, atl, tsb) or (None, None, None) if insufficient data.
    """
    if len(daily_tss) < 7:
        return None, None, None

    acute_decay = 2 / (acute_window + 1)
    chronic_decay = 2 / (chronic_window + 1)

    atl = daily_tss[0]
    ctl = daily_tss[0]

    for val in daily_tss[1:]:
        atl = val * acute_decay + atl * (1 - acute_decay)
        ctl = val * chronic_decay + ctl * (1 - chronic_decay)

    tsb = ctl - atl
    return round(ctl, 1), round(atl, 1), round(tsb, 1)


def compute_acwr(atl: float | None, ctl: float | None) -> float | None:
    """Acute:Chronic Workload Ratio. Target 0.8-1.3, > 1.5 = injury risk."""
    if not atl or not ctl or ctl <= 0:
        return None
    return round(atl / ctl, 2)


def estimate_vo2max(resting_hr: float | None, max_hr: float | None,
                    age: int | None = None,
                    pace_seconds: float | None = None,
                    avg_hr: float | None = None) -> float | None:
    """Estimate VO2 max using best available data.

    Method 1 (preferred): Pace-based with HR fraction (if pace + avg_hr available)
    Method 2 (fallback): Uth formula (15.3 * max_hr / resting_hr)
    """
    if age and max_hr is None:
        max_hr = int(208 - 0.7 * age)

    # Method 1: Pace-based (most accurate for runners)
    if pace_seconds and avg_hr and max_hr and resting_hr and pace_seconds > 0:
        speed_m_per_min = 1609.34 / (pace_seconds / 60)
        speed_km_h = speed_m_per_min * 60 / 1000
        if speed_km_h > 8:
            vo2_running = 2.209 + (3.1633 * speed_km_h)
        else:
            vo2_running = (0.2 * speed_m_per_min) + 3.5
        hr_reserve = max_hr - resting_hr
        if hr_reserve > 0:
            hr_fraction = (avg_hr - resting_hr) / hr_reserve
            if 0.3 < hr_fraction < 1.0:
                return round(vo2_running / hr_fraction, 1)

    # Method 2: Uth formula (HR-only)
    if max_hr and resting_hr and resting_hr > 0:
        return round(15.3 * (max_hr / resting_hr), 1)

    return None


def compute_zone2_minutes(zone_data: dict) -> int:
    """Compute Zone 2 time from Whoop zone data (milliseconds).

    Whoop Zone 1 (50-60% max HR) + Zone 2 (60-70% max HR) ≈ physiological Zone 2.
    """
    z1 = zone_data.get("zone_one_milli") or 0
    z2 = zone_data.get("zone_two_milli") or 0
    total_ms = z1 + z2
    return round(total_ms / 60000)


def vdot_paces(vdot: float) -> dict:
    """Return pace targets (seconds/mile) for all workout types from VDOT."""
    if not vdot or vdot <= 0:
        return {"easy": 540, "marathon": 510, "tempo": 450, "interval": 420, "repetition": 390}
    easy = max(420, 660 - (vdot - 30) * 6)
    marathon = max(380, 600 - (vdot - 30) * 5.5)
    tempo = max(350, 540 - (vdot - 30) * 5)
    interval = max(310, 490 - (vdot - 30) * 4.5)
    repetition = max(280, 450 - (vdot - 30) * 4)
    return {"easy": easy, "marathon": marathon, "tempo": tempo, "interval": interval, "repetition": repetition}


def compute_hr_zones(max_hr: int) -> dict:
    """Return HR zone boundaries from max HR."""
    if not max_hr:
        return {}
    return {
        "recovery": int(max_hr * 0.65),
        "easy_cap": int(max_hr * 0.76),
        "marathon_low": int(max_hr * 0.80),
        "marathon_high": int(max_hr * 0.85),
        "tempo": int(max_hr * 0.88),
        "interval_low": int(max_hr * 0.93),
        "interval_high": int(max_hr * 0.98),
    }


# ── Weekly Scorecard ─────────────────────────────────────────────


@dataclass
class GoalProgress:
    label: str       # "Weight", "Marathon", "Body Fat"
    current: str     # "194.4 lbs"
    target: str      # "185 lbs"
    trend: str       # "↓ 1.6/wk"
    status: str      # "on_track" | "building" | "stalling" | "off_track"


@dataclass
class WeeklyScorecard:
    week_ending: str
    goals: list
    nutrition_compliance: dict
    zone2_minutes: int
    zone2_target: int
    avg_recovery: float | None
    weekly_miles: float
    headline: str


def compute_weekly_scorecard(
    current_weight: float | None,
    goal_weight: float | None,
    weight_7d_ago: float | None,
    vdot: float | None,
    goal_marathon_min: float | None,
    ef_trend: str | None,
    current_bf: float | None,
    goal_bf: float | None,
    bf_30d_ago: float | None,
    nutrition_days: int,
    nutrition_hit_cal: int,
    nutrition_hit_protein: int,
    zone2_minutes: int,
    avg_recovery: float | None,
    weekly_miles: float,
    week_ending: str,
) -> WeeklyScorecard:
    """Compute the weekly scorecard from aggregated data."""
    goals = []

    # Weight goal
    if current_weight and goal_weight:
        weekly_change = round(current_weight - weight_7d_ago, 1) if weight_7d_ago else None
        remaining = round(current_weight - goal_weight, 1)

        if weekly_change is not None and weekly_change < 0:
            rate = abs(weekly_change)
            if 0.5 <= rate <= 2.0:
                status = "on_track"
            elif rate > 2.0:
                status = "on_track"  # losing fast but still progress
            else:
                status = "building"  # slow but moving
            trend = f"↓ {rate}/wk"
        elif weekly_change is not None and weekly_change > 0.5:
            status = "off_track"
            trend = f"↑ {weekly_change}/wk"
        else:
            status = "building" if remaining > 0 else "on_track"
            trend = "→ flat"

        goals.append(GoalProgress(
            label="Weight",
            current=f"{current_weight} lbs",
            target=f"{goal_weight} lbs",
            trend=trend,
            status=status,
        ))

    # Marathon goal
    if vdot and goal_marathon_min:
        marathon_est = vdot_to_marathon_time(vdot)
        hours = int(goal_marathon_min // 60)
        mins = int(goal_marathon_min % 60)
        goal_str = f"{hours}:{mins:02d}"

        if ef_trend == "improving":
            status = "on_track"
            trend = "EF ↑ improving"
        elif ef_trend == "plateau":
            status = "building"
            trend = "EF → plateau"
        else:
            status = "stalling"
            trend = "EF ↓ declining"

        goals.append(GoalProgress(
            label="Marathon",
            current=f"~{marathon_est}",
            target=f"sub-{goal_str}",
            trend=trend,
            status=status,
        ))

    # Body fat goal
    if current_bf and goal_bf:
        if bf_30d_ago and current_bf < bf_30d_ago:
            status = "on_track"
            trend = f"↓ {round(bf_30d_ago - current_bf, 1)}% in 30d"
        elif bf_30d_ago and current_bf >= bf_30d_ago:
            status = "off_track"
            trend = "→ no change"
        else:
            status = "building"
            trend = "Need more data"

        goals.append(GoalProgress(
            label="Body Fat",
            current=f"{current_bf}%",
            target=f"{goal_bf}%",
            trend=trend,
            status=status,
        ))

    # Nutrition compliance
    cal_pct = round(nutrition_hit_cal / nutrition_days * 100) if nutrition_days > 0 else 0
    protein_pct = round(nutrition_hit_protein / nutrition_days * 100) if nutrition_days > 0 else 0

    # Headline
    on_track_count = sum(1 for g in goals if g.status in ("on_track", "building"))
    total = len(goals) if goals else 1
    if on_track_count == total and total > 0:
        headline = "Strong week — on track across all goals."
    elif on_track_count >= total * 0.5:
        headline = "Solid progress — most goals moving in the right direction."
    elif goals:
        headline = "Needs attention — check the areas falling behind."
    else:
        headline = "Set your goals in Settings to track progress."

    return WeeklyScorecard(
        week_ending=week_ending,
        goals=[{"label": g.label, "current": g.current, "target": g.target, "trend": g.trend, "status": g.status} for g in goals],
        nutrition_compliance={"calories_pct": cal_pct, "protein_pct": protein_pct},
        zone2_minutes=zone2_minutes,
        zone2_target=150,
        avg_recovery=avg_recovery,
        weekly_miles=round(weekly_miles, 1),
        headline=headline,
    )


def prescribe_workout(recovery_score: float | None,
                      tsb: float | None,
                      acwr: float | None,
                      vdot: float | None,
                      max_hr: int | None) -> WorkoutRx:
    """Prescribe today's workout based on recovery + training load + goals.

    VDOT pace targets for sub-3 marathon (VDOT ~54):
    - Easy: ~8:30-9:15/mi
    - Tempo: ~6:25-6:35/mi
    - Interval: ~5:50-6:10/mi
    """
    # Default paces based on VDOT (or generic if no VDOT)
    if vdot and vdot > 0:
        # Approximate pace targets from VDOT
        easy_pace_sec = max(420, 660 - (vdot - 30) * 6)  # ~8:30 at VDOT 54
        tempo_pace_sec = max(350, 540 - (vdot - 30) * 5)
    else:
        easy_pace_sec = 540  # 9:00/mi default
        tempo_pace_sec = 450  # 7:30/mi default

    hr_cap = int(max_hr * 0.75) if max_hr else None

    # Decision tree
    if (recovery_score is not None and recovery_score < 33) or (acwr is not None and acwr > 1.5):
        return WorkoutRx(
            type="rest",
            distance_miles=0,
            pace_min="",
            pace_max="",
            hr_cap=None,
            description="Rest day or very easy 2-3 mile jog",
            rationale=f"Recovery is low ({recovery_score:.0f}%)" if recovery_score is not None else "Training load spike detected (ACWR > 1.5)"
        )

    if (recovery_score is not None and recovery_score < 50) or (tsb is not None and tsb < -20):
        return WorkoutRx(
            type="easy",
            distance_miles=4,
            pace_min=_secs_to_pace(easy_pace_sec),
            pace_max=_secs_to_pace(easy_pace_sec + 30),
            hr_cap=hr_cap,
            description=f"Easy run — 4 miles at {_secs_to_pace(easy_pace_sec)}-{_secs_to_pace(easy_pace_sec + 30)}/mi",
            rationale="Recovery is moderate. Keep it easy and build aerobic base."
        )

    if recovery_score is not None and recovery_score >= 67:
        return WorkoutRx(
            type="tempo",
            distance_miles=7,
            pace_min=_secs_to_pace(tempo_pace_sec),
            pace_max=_secs_to_pace(tempo_pace_sec + 15),
            hr_cap=int(max_hr * 0.88) if max_hr else None,
            description=f"Tempo run — 7 miles with 3mi at {_secs_to_pace(tempo_pace_sec)}/mi",
            rationale=f"Recovery is strong ({recovery_score:.0f}%). Good day for quality work."
        )

    # Default: easy-moderate
    return WorkoutRx(
        type="easy",
        distance_miles=6,
        pace_min=_secs_to_pace(easy_pace_sec),
        pace_max=_secs_to_pace(easy_pace_sec + 30),
        hr_cap=hr_cap,
        description=f"Easy run — 6 miles at {_secs_to_pace(easy_pace_sec)}-{_secs_to_pace(easy_pace_sec + 30)}/mi",
        rationale="Solid day to build aerobic volume."
    )


# ── VO2max categorization ─────────────────────────────────────────


def categorize_vo2max(vo2max: float | None) -> str | None:
    """Classify VO2max into a fitness category."""
    if not vo2max:
        return None
    if vo2max >= 50:
        return "Elite"
    if vo2max >= 45:
        return "Above Average"
    if vo2max >= 40:
        return "Average"
    if vo2max >= 35:
        return "Below Average"
    return "Low"


# ── Biological Age (ACSM 50th percentile VO2max tables) ──────────

# ── Nutrition plan (Mifflin-St Jeor + deficit math) ──────────────


@dataclass
class NutritionPlan:
    rmr: int                    # Mifflin-St Jeor RMR or user override (kcal/day)
    rmr_adapted: int            # RMR × 0.90 if cutting, else RMR
    workout_calories: int       # From Whoop kilojoules today (0 on rest days)
    daily_budget: int           # rmr_adapted + workout_calories
    protein_target_grams: int   # 1g per lb of current weight
    is_cutting: bool            # True if goal_weight < current_weight
    warning: str | None


def compute_rmr(weight_lbs: float, height_inches: int, age: int, sex: str) -> int:
    """Mifflin-St Jeor RMR. The evidence-based standard (ADA, 2005)."""
    weight_kg = weight_lbs / 2.205
    height_cm = height_inches * 2.54
    rmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age)
    rmr += 5 if sex == "male" else -161
    return round(rmr)


def compute_nutrition_plan(
    weight_lbs: float,
    height_inches: int,
    age: int,
    sex: str,
    goal_weight_lbs: float | None = None,
    workout_calories: int = 0,
    rmr_override: int | None = None,
) -> NutritionPlan:
    """Workout-based daily budget: Adapted RMR + actual workout burn.

    Uses rmr_override if provided, otherwise Mifflin-St Jeor.
    Metabolic adaptation (×0.90) only applied during active cut.
    """
    rmr = rmr_override if rmr_override else compute_rmr(weight_lbs, height_inches, age, sex)

    is_cutting = bool(goal_weight_lbs and weight_lbs > goal_weight_lbs)
    rmr_adapted = round(rmr * 0.90) if is_cutting else rmr

    daily_budget = rmr_adapted + workout_calories
    protein = max(round(weight_lbs * 1.0), 150)

    return NutritionPlan(
        rmr=rmr,
        rmr_adapted=rmr_adapted,
        workout_calories=workout_calories,
        daily_budget=daily_budget,
        protein_target_grams=protein,
        is_cutting=is_cutting,
        warning=None,
    )


# ── VDOT ↔ Marathon time ────────────────────────────────────────


def vdot_to_marathon_time(vdot: float) -> str:
    """Convert VDOT to estimated marathon time string like '3:18'.

    Uses the inverse of the linear fit in estimate_vdot().
    """
    if not vdot or vdot <= 30:
        return "N/A"
    pace_sec = (97.0 - vdot) / 0.1
    marathon_sec = pace_sec * 26.2
    hours = int(marathon_sec // 3600)
    mins = int((marathon_sec % 3600) // 60)
    return f"{hours}:{mins:02d}"
