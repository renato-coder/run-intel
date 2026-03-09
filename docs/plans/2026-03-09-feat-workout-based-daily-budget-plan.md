---
title: "feat: Replace TDEE with workout-based daily calorie budget"
type: feat
status: completed
date: 2026-03-09
---

# Replace TDEE with Workout-Based Daily Calorie Budget

## Overview

The current nutrition model uses a static TDEE multiplier (RMR × 0.90 × 1.55) that doesn't reflect actual daily activity. Replace it with a simple, accurate model: **Daily Budget = Adapted RMR + Actual Workout Calories Burned (from Whoop)**. Then show: budget minus intake = over or under.

## Problem Statement

The user's measured RMR is 2,100. The app applies a 1.55 "moderately active" multiplier to get TDEE of 2,930 — a number that means nothing and isn't accurate on rest days vs. hard workout days. The user wants to see what they actually burned today and whether they ate more or less than that.

## New Model

```
RMR (user-set or calculated)
  → Adapted RMR = RMR × 0.90 (only when in active deficit, i.e. goal_weight < current_weight)
  → Daily Budget = Adapted RMR + Whoop Workout Calories Burned today
  → Net = Daily Budget - Calories Eaten today
    positive → "under budget" (in deficit, losing weight)
    negative → "over budget" (in surplus)
```

**On rest days (no workout):** Budget = Adapted RMR only.
**Multiple workouts:** Sum all kilojoules from all Whoop workouts today (not just running).
**No metabolic adaptation if not cutting:** If no goal weight is set, or current weight ≤ goal weight, Adapted RMR = RMR (no 0.90 factor).

## Key Decisions

1. **Remove TDEE entirely.** No more 1.55 multiplier. No more "TDEE" label anywhere in the UI.
2. **Remove day_type calorie adjustments.** The workout-based budget already accounts for intensity — a hard workout naturally burns more kilojoules. No more hard/easy/rest multipliers on top.
3. **Keep deficit/goal system as context only.** If the user has a goal weight + target date, show "at this rate, you'll hit X lbs in Y weeks" based on their 7-day average net deficit. But don't use it to set a target — the budget IS the target.
4. **Custom calorie target overrides everything.** If `goal_calorie_target` is set, use that as the budget (ignoring RMR + workout). Same as today.
5. **Metabolic adaptation (0.90) only during active cut.** Apply when `goal_weight_lbs` is set AND `current_weight > goal_weight_lbs`. Otherwise RMR is used as-is.
6. **Whoop kilojoule field:** `score.kilojoule` on workout objects. Convert to kcal: `kilojoule / 4.184`. This field exists in Whoop API v2 (same `score` object that has `strain`, `average_heart_rate`, etc.).
7. **Budget is a snapshot at page load.** No real-time polling. If user does a workout and comes back, switching to the Nutrition tab re-fetches the briefing. Add a small note if no workout calories found: "Workout calories update after Whoop syncs."
8. **No caching workout calories in DB.** Keep it simple — fetch from Whoop API on each briefing call. Recovery is already fetched there; adding workouts is one more API call. Single-user app, latency is acceptable.
9. **"Today" for workouts:** Use `whoop_query_window()` (±1 day padding) centered on UTC today, then filter results to workouts whose `start` timestamp falls on UTC today. This is the same approach used for run logging. Not perfect for late-night MST workouts, but acceptable for a single-user app.

## Technical Approach

### Backend Changes

**`src/services/coaching.py`**

Simplify `NutritionPlan` dataclass:

```python
@dataclass
class NutritionPlan:
    rmr: int                      # User-set or Mifflin-St Jeor
    rmr_adapted: int              # RMR × 0.90 if cutting, else RMR
    workout_calories: int         # From Whoop kilojoules today (0 if rest day)
    daily_budget: int             # rmr_adapted + workout_calories
    protein_target_grams: int     # 1g per lb body weight
    is_cutting: bool              # True if goal_weight < current_weight
    warning: str | None
```

Remove from dataclass: `tdee`, `daily_deficit`, `calorie_target`, `weekly_loss_rate`, `weeks_to_goal`, `is_safe`.

Update `compute_nutrition_plan()`:
- Remove `activity_multiplier` parameter
- Add `workout_calories: int = 0` parameter
- Apply 0.90 adaptation only when cutting
- `daily_budget = rmr_adapted + workout_calories`
- Remove deficit/target/safety logic from here (move weekly stats to frontend or a separate function)

**`src/routes/briefing.py`**

Add workout calorie fetching alongside recovery:

```python
def _fetch_today_workout_calories(session):
    """Sum kilojoules from all Whoop workouts today, return kcal."""
    from whoop import WhoopClient
    from utils import whoop_query_window

    today = datetime.now(timezone.utc).date()
    try:
        client = WhoopClient()
        start = whoop_query_window(today)
        workouts = client.get_workouts(start=start)
        total_kj = 0
        for w in workouts:
            # Filter to workouts that started today (UTC)
            w_start = w.get("start")
            if w_start:
                w_date = datetime.fromisoformat(w_start.replace("Z", "+00:00")).date()
                if w_date != today:
                    continue
            score = w.get("score", {})
            kj = score.get("kilojoule") or 0
            total_kj += kj
        return round(total_kj / 4.184)
    except Exception:
        logger.exception("Error fetching workout calories from Whoop")
        return 0
```

Update the nutrition_target assembly:
- Call `_fetch_today_workout_calories()` in `get_briefing()`
- Pass `workout_calories` to `compute_nutrition_plan()`
- Determine if user is cutting: `is_cutting = goal_weight_lbs and current_weight > goal_weight_lbs`
- Remove day_type calorie adjustments (hard/easy/rest multipliers)
- New response shape (see below)

**New nutrition_target response:**

```json
{
  "calories": 2510,
  "protein_grams": 196,
  "rmr": 2100,
  "rmr_adapted": 1890,
  "workout_calories": 620,
  "daily_budget": 2510,
  "is_cutting": true,
  "target_source": "auto",
  "warning": null,
  "today": {
    "calories": 2426,
    "protein_grams": 175
  },
  "net": -84,
  "yesterday": {
    "calories": 2426,
    "protein_grams": 175
  }
}
```

Where:
- `calories` = the target (= `daily_budget`, or `goal_calorie_target` if custom override)
- `net` = `calories` (target) - `today.calories` (eaten). Positive = remaining, negative = over.
- `today` = sum of today's NutritionLog entries (replaces the existing yesterday-only data)
- Remove: `tdee`, `daily_deficit`, `weekly_loss_rate`, `weeks_to_goal`, `is_safe`, `day_type`

**`src/routes/briefing.py` — today's nutrition**

Currently only fetches yesterday's nutrition. Add today's nutrition query:

```python
today_nutrition = (
    session.query(NutritionLog)
    .filter(NutritionLog.date == today)
    .all()
)
today_cals = sum(n.calories for n in today_nutrition) if today_nutrition else 0
today_protein = sum(n.protein_grams for n in today_nutrition) if today_nutrition else 0
```

### Frontend Changes

**`src/static/index.html` — NutritionTab**

Replace "YOUR METABOLISM BREAKDOWN" card:

```
Current (4 columns):  RMR → Adapted (-10%) → TDEE → Target

New (3 or 4 columns depending on workout):

Rest day (no workout):
  Adapted RMR: 1,890  |  Workout: —  |  Budget: 1,890

Workout day:
  Adapted RMR: 1,890  |  Workout: +620  |  Budget: 2,510

If not cutting (no adaptation):
  RMR: 2,100  |  Workout: +620  |  Budget: 2,720
```

Replace daily feedback sentence:

```
Current: "You ate 2,426 cal — 29 under your 2,455 target. On track."

New examples:
- "Budget: 1,890 + 620 (workout) = 2,510. You ate 2,426. 84 cal remaining."
- "Budget: 1,890 (rest day). You ate 2,100. 210 cal over budget."
- "Budget: 2,510. No meals logged yet."
```

Remove:
- "Rest day (deficit) — targets adjusted for today's workout" label
- "Daily deficit: 375 cal (0.75 lbs/week)" line
- "Weeks to goal" line from metabolism breakdown
- All references to "TDEE"

Add:
- Small note below budget when workout_calories = 0: "Workout calories update after Whoop syncs"
- Keep protein tracking as-is (196g target, percentage display)

**`src/static/index.html` — SettingsTab**

Replace the Nutrition Targets hint text:

```
Current: "TDEE ~2,930 cal/day. Leave blank to auto-calculate from your RMR."
New: "Your daily budget = Adapted RMR + workout calories. Leave blank to auto-calculate."
```

Remove auto-calculation of `rmrUsed * 0.9 * 1.55` for preview. The budget is dynamic, can't be previewed in Settings.

## Files to Modify

| File | Changes |
|------|---------|
| `src/services/coaching.py` | Simplify `NutritionPlan`, update `compute_nutrition_plan()` — remove TDEE/deficit, add `workout_calories` |
| `src/routes/briefing.py` | Add `_fetch_today_workout_calories()`, fetch today's nutrition, new response shape |
| `src/static/index.html` | NutritionTab: new budget display, new feedback sentence. SettingsTab: remove TDEE hint |

No new dependencies. No schema changes. No new DB tables.

## Acceptance Criteria

- [x] `NutritionPlan` dataclass has `rmr`, `rmr_adapted`, `workout_calories`, `daily_budget`, `protein_target_grams`, `is_cutting`
- [x] `compute_nutrition_plan()` no longer takes `activity_multiplier`; takes `workout_calories` instead
- [x] Metabolic adaptation (0.90) only applied when user is in active cut (goal_weight < current_weight)
- [x] Briefing fetches today's Whoop workouts and sums kilojoules across all workout types
- [x] `nutrition_target` response includes `workout_calories`, `daily_budget`, `today.calories`, `net`
- [x] No references to "TDEE" anywhere in the codebase or UI
- [x] No day_type calorie adjustments (hard/easy/rest multipliers removed)
- [x] Metabolism breakdown shows: Adapted RMR + Workout = Budget (not RMR → TDEE → Target)
- [x] Daily feedback: "Budget: X. You ate Y. Z remaining/over."
- [x] Rest days show budget = Adapted RMR, no "0" workout column
- [x] Custom calorie target still overrides the auto budget when set
- [x] Protein target unchanged (1g/lb body weight)
- [x] Whoop API failure gracefully degrades to workout_calories = 0
- [x] Settings page no longer shows TDEE preview

## Recommended Build Order

1. **Backend first** — Update `coaching.py` dataclass + function, then `briefing.py` route
2. **Frontend second** — Update NutritionTab display and SettingsTab hint
3. **Clean up** — Remove all TDEE references, dead code from day_type adjustments
