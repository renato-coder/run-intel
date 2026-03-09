"""
Metrics orchestration — fetch data, call coaching functions, return results.

This is the layer between route handlers and pure computation.
"""

from datetime import datetime, timedelta, timezone

from database import Recovery, Run, UserProfile
from services.coaching import (
    MetricsSnapshot,
    compute_acwr,
    compute_efficiency_factor,
    compute_training_load,
    compute_tss,
    compute_zone2_minutes,
    estimate_vdot,
    estimate_vo2max,
)
from utils import pace_str_to_seconds


def get_current_metrics(session, profile: UserProfile | None = None) -> MetricsSnapshot:
    """Compute all current metrics from run history + profile.

    Returns a MetricsSnapshot with whatever data is available.
    """
    today = datetime.now(timezone.utc).date()
    cutoff_90d = today - timedelta(days=90)
    cutoff_30d = today - timedelta(days=30)
    cutoff_7d = today - timedelta(days=7)

    # Fetch runs for the last 90 days
    runs = (
        session.query(Run)
        .filter(Run.date >= cutoff_90d, Run.date <= today)
        .order_by(Run.date)
        .all()
    )

    if not runs:
        return MetricsSnapshot(
            ef_30d=None, ef_90d=None, ef_trend=None, vdot=None,
            ctl=None, atl=None, tsb=None, acwr=None,
            estimated_vo2max=None, zone2_minutes_week=None,
        )

    # Compute EF for each run
    ef_values_30d = []
    ef_values_90d = []
    for r in runs:
        pace_sec = pace_str_to_seconds(r.pace_per_mile)
        if pace_sec and r.avg_hr:
            ef = compute_efficiency_factor(pace_sec, r.avg_hr)
            if ef:
                ef_values_90d.append(ef)
                if r.date >= cutoff_30d:
                    ef_values_30d.append(ef)

    ef_30d = round(sum(ef_values_30d) / len(ef_values_30d), 2) if ef_values_30d else None
    ef_90d = round(sum(ef_values_90d) / len(ef_values_90d), 2) if ef_values_90d else None

    ef_trend = None
    if ef_30d and ef_90d:
        diff_pct = (ef_30d - ef_90d) / ef_90d * 100
        if diff_pct > 2:
            ef_trend = "improving"
        elif diff_pct < -2:
            ef_trend = "declining"
        else:
            ef_trend = "plateau"

    # VDOT from best recent effort (fastest pace with HR data in last 90d)
    vdot = None
    best_pace_run = None
    for r in runs:
        pace_sec = pace_str_to_seconds(r.pace_per_mile)
        if pace_sec and r.avg_hr and r.distance_miles and r.distance_miles >= 3:
            if best_pace_run is None or pace_sec < pace_str_to_seconds(best_pace_run.pace_per_mile):
                best_pace_run = r
    if best_pace_run:
        vdot = estimate_vdot(best_pace_run.distance_miles, best_pace_run.time_minutes)

    # TSS + training load
    threshold_hr = None
    if profile and profile.max_hr:
        threshold_hr = int(profile.max_hr * 0.88)
    elif profile and profile.age:
        threshold_hr = int((208 - 0.7 * profile.age) * 0.88)

    # Build daily TSS array for 90 days
    daily_tss = []
    day = cutoff_90d
    run_by_date = {}
    for r in runs:
        run_by_date.setdefault(r.date, []).append(r)

    while day <= today:
        day_runs = run_by_date.get(day, [])
        day_tss = 0
        for r in day_runs:
            if r.time_minutes and r.avg_hr and threshold_hr:
                tss = compute_tss(r.time_minutes, r.avg_hr, threshold_hr)
                if tss:
                    day_tss += tss
        daily_tss.append(day_tss)
        day += timedelta(days=1)

    ctl, atl, tsb = compute_training_load(daily_tss)
    acwr = compute_acwr(atl, ctl)

    # VO2 max estimation
    resting_hr = float(profile.resting_hr_baseline) if profile and profile.resting_hr_baseline else None
    max_hr_val = profile.max_hr if profile else None
    age_val = profile.age if profile else None

    # If no resting HR from profile, try Whoop recovery
    if resting_hr is None:
        recent_recovery = (
            session.query(Recovery)
            .filter(Recovery.resting_hr.isnot(None))
            .order_by(Recovery.date.desc())
            .limit(30)
            .all()
        )
        if recent_recovery:
            resting_hr = round(sum(r.resting_hr for r in recent_recovery) / len(recent_recovery), 1)

    # Use easiest recent runs for VO2 max estimation (Zone 2 runs)
    vo2max = None
    easy_runs = [r for r in runs if r.date >= cutoff_30d
                 and r.avg_hr and pace_str_to_seconds(r.pace_per_mile)
                 and r.distance_miles and r.distance_miles >= 3]
    if easy_runs and resting_hr:
        vo2_estimates = []
        for r in easy_runs[-10:]:
            pace_sec = pace_str_to_seconds(r.pace_per_mile)
            est = estimate_vo2max(
                resting_hr=resting_hr,
                max_hr=max_hr_val,
                age=age_val,
                pace_seconds=pace_sec,
                avg_hr=r.avg_hr,
            )
            if est and 25 < est < 80:
                vo2_estimates.append(est)
        if vo2_estimates:
            vo2max = round(sum(vo2_estimates) / len(vo2_estimates), 1)
    elif resting_hr:
        vo2max = estimate_vo2max(resting_hr=resting_hr, max_hr=max_hr_val, age=age_val)

    # Zone 2 minutes this week
    week_runs = [r for r in runs if r.date >= cutoff_7d]
    z2_total = 0
    for r in week_runs:
        z2_total += compute_zone2_minutes({
            "zone_one_milli": r.zone_one_milli,
            "zone_two_milli": r.zone_two_milli,
        })

    return MetricsSnapshot(
        ef_30d=ef_30d,
        ef_90d=ef_90d,
        ef_trend=ef_trend,
        vdot=vdot,
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        acwr=acwr,
        estimated_vo2max=vo2max,
        zone2_minutes_week=z2_total,
    )
