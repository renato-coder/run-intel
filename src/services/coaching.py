"""
Pure computation functions for coaching metrics.

No database access — all functions take data in, return results out.
"""

from dataclasses import dataclass
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

# ACSM Guidelines 11th ed., FRIEND registry — 50th percentile VO2max
# Format: list of (age_midpoint, vo2max) sorted youngest to oldest
_ACSM_MALE = [(25, 42.5), (35, 41.0), (45, 38.5), (55, 35.0), (65, 31.0), (75, 27.0)]
_ACSM_FEMALE = [(25, 35.2), (35, 33.8), (45, 31.6), (55, 28.7), (65, 25.2), (75, 22.5)]


def _vo2max_to_bio_age(vo2max: float, table: list[tuple[int, float]]) -> float:
    """Interpolate VO2max to biological age using ACSM 50th percentile table."""
    # Above youngest group — extrapolate with dampened rate
    if vo2max >= table[0][1]:
        excess = vo2max - table[0][1]
        return max(18.0, table[0][0] - excess * 0.8)

    # Below oldest group — extrapolate using last two groups' slope
    if vo2max <= table[-1][1]:
        age_old, vo2_old = table[-1]
        age_prev, vo2_prev = table[-2]
        slope = (age_old - age_prev) / (vo2_prev - vo2_old)
        deficit = vo2_old - vo2max
        return min(85.0, age_old + deficit * slope)

    # Linear interpolation between adjacent groups
    for i in range(len(table) - 1):
        age_young, vo2_young = table[i]
        age_old, vo2_old = table[i + 1]
        if vo2max <= vo2_young and vo2max >= vo2_old:
            ratio = (vo2_young - vo2max) / (vo2_young - vo2_old)
            return age_young + ratio * (age_old - age_young)

    return table[-1][0]  # fallback


def _rhr_adjustment(rhr: float | None) -> float:
    """RHR-based biological age adjustment (±2 years max)."""
    if rhr is None:
        return 0.0
    if rhr < 45:
        return -2.0
    if rhr < 50:
        return -1.0
    if rhr <= 69:
        return 0.0
    if rhr <= 79:
        return 1.0
    return 2.0


def _hrv_adjustment(hrv: float | None) -> float:
    """HRV (RMSSD ms) based biological age adjustment (±2 years max)."""
    if hrv is None:
        return 0.0
    if hrv >= 90:
        return -2.0
    if hrv >= 70:
        return -1.0
    if hrv >= 20:
        return 0.0
    if hrv >= 12:
        return 1.0
    return 2.0


@dataclass
class BiologicalAgeResult:
    biological_age: float
    chronological_age: int
    delta: float           # negative = younger
    aging_direction: str   # "improving" | "stable" | "declining"
    disclaimer: str


def compute_biological_age(
    vo2max: float,
    sex: str,
    age: int,
    rhr: float | None = None,
    hrv: float | None = None,
) -> BiologicalAgeResult:
    """Compute biological age from VO2max + optional RHR/HRV adjustments."""
    table = _ACSM_MALE if sex == "male" else _ACSM_FEMALE
    base_bio_age = _vo2max_to_bio_age(vo2max, table)
    adjustment = _rhr_adjustment(rhr) + _hrv_adjustment(hrv)
    bio_age = round(max(18, min(85, base_bio_age + adjustment)))
    delta = bio_age - age
    return BiologicalAgeResult(
        biological_age=bio_age,
        chronological_age=age,
        delta=delta,
        aging_direction="stable",  # caller should set from trend data
        disclaimer="Estimate based on cardiorespiratory fitness (ACSM tables)",
    )
