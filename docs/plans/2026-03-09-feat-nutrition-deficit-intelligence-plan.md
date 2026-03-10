---
title: "feat: Nutrition Deficit Intelligence + Weekly Plan Fixes"
type: feat
status: active
date: 2026-03-09
---

# Nutrition Deficit Intelligence + Weekly Plan Fixes

## Overview

Transform the Nutrition tab from a logging tool into a deficit-aware coach. The user wants to see — at a glance — whether their week is on track for weight loss. Three nutrition features + two weekly plan UX fixes.

## Problem Statement

The Nutrition tab currently shows a daily budget and compliance percentages, but never answers the key question: **"Am I in enough of a deficit this week to actually lose weight?"** The user logs meals but has no visibility into:
1. What their actual calorie deficit was for each past day
2. What weekly deficit they need to hit their weight loss goal (196 → 185 lbs)
3. Whether the current week's cumulative deficit is on track

Additionally, the weekly plan has two UX issues: Monday shows 2mi instead of 3mi (cutback triggers too aggressively for Monday), and the dashboard shows conflicting "Today's Workout" sections from two different sources.

## Proposed Solution

### Feature 1: Daily Deficit in Nutrition Logs

Show the calorie deficit for each day in the Recent Entries section. Group entries by date with a header row showing: **date, total calories, total protein, and deficit** (budget - intake).

**Deficit calculation:** `deficit = (rmr_adapted + workout_calories) - total_calories_eaten`

**Historical budget problem:** The system only computes today's budget live (RMR + Whoop API call). For past days, we need stored workout calories.

**Decision D1: Add `kilojoule` column to Workout model.** The Whoop sync already stores workouts but discards kilojoule data. Store it. For past days, compute `workout_calories = sum(kilojoules) / 4.184` from stored Workout rows. For days with no stored workout data, fall back to RMR-only budget (show as dimmed/approximate).

### Feature 2: Weekly Deficit Target

Calculate and display the weekly calorie deficit needed to reach goal weight by target date.

```
lbs_to_lose = current_weight - goal_weight
weeks_remaining = (goal_target_date - today).days / 7
weekly_deficit_needed = lbs_to_lose * 3500 / weeks_remaining
daily_deficit_needed = weekly_deficit_needed / 7
```

**Decision D2: Safety bounds.**
- If `weeks_remaining <= 0`: show "Target date has passed — update in Settings"
- If `weekly_deficit_needed > 7000` (>2 lbs/week): show warning "This pace requires losing more than 2 lbs/week. Consider extending your target date."
- If `current_weight <= goal_weight`: show "Goal reached!" in green
- If `goal_weight` or `goal_target_date` not set: show "Set a weight goal and target date in Settings"

### Feature 3: Weekly Deficit Bar Chart

A bar chart showing daily deficits Mon–Sun for the current week:
- Each bar = that day's deficit (budget - intake). Positive = deficit (good). Negative = surplus (over budget).
- Horizontal dashed line = daily deficit needed to stay on track (from Feature 2)
- Bar color: green if >= daily target, red if below
- Show bars only for days up through today. Future days show as empty labeled slots.
- Days with no nutrition logs show no bar (not a false "full deficit").

**Decision D3: Use custom Chart.js afterDraw hook** for the target line (no new plugin dependency). The codebase already uses Chart.js from CDN with no plugins.

**Decision D4: New API endpoint `GET /api/nutrition/weekly-summary?local_date=`** returns per-day data for the week:
```json
{
  "days": [
    {"date": "2026-03-03", "calories_in": 1850, "protein_in": 165, "budget": 2350, "deficit": 500, "workout_cal": 450},
    ...
  ],
  "weekly_deficit_target": 3500,
  "weekly_deficit_actual": 2100,
  "weekly_deficit_remaining": 1400,
  "goal_context": {"current_weight": 196, "goal_weight": 185, "weeks_remaining": 12.3}
}
```

### Feature 4: Fix Monday Run Miles

**Root cause:** `mon_miles = min(easy_per_day, 3) if not cutback else 2` — cutback drops Monday to 2mi.

**Decision D5: Monday always gets 3mi minimum.** The 1mi reduction saves negligible training load but confuses the user. Monday already has a 45-min lift; the combined session is inherently moderate. Apply cutback volume reductions to Thursday (volume day) and Sunday (long run) where the impact is meaningful.

Change in `src/services/weekly_planner.py:149`:
```python
# Before:
mon_miles = min(easy_per_day, 3) if not cutback else 2
# After:
mon_miles = 3
```

### Feature 5: Fix Conflicting Workout Display

**Problem:** Dashboard shows "Today's Workout" in both the `TodayWorkoutCard` (from weekly plan) AND inside the `MorningBriefing` card (from `prescribe_workout()` in briefing engine).

**Decision D6: Relabel the briefing's workout section to "Recovery Check."** Only show it when recovery is notably different from plan assumptions (recovery < 50%). This preserves the adaptive capability without showing two conflicting workout titles. The weekly plan's `TodayWorkoutCard` remains the authoritative workout source.

In `src/static/index.html`, inside the `MorningBriefing` component:
- Change label from "Today's Workout" to "Recovery Check"
- Only render the section if recovery score is available and suggests plan modification
- Show the `recovery_adjustment` note from the plan, not a separate workout prescription

## Technical Approach

### Backend Changes

#### `src/database.py`
- [x] Add `kilojoule` column (Float, nullable) to `Workout` model
- [x] Add migration: `ALTER TABLE workouts ADD COLUMN IF NOT EXISTS kilojoule FLOAT`

#### `src/routes/weekly.py` — Whoop Sync
- [x] Store `score.get("kilojoule")` during `_sync_whoop_workouts()`

#### `src/services/coaching.py`
- [x] Add `compute_weekly_deficit_target(current_weight, goal_weight, goal_target_date, today)` → dict with safety bounds (daily deficit is a one-liner, inline in route)

#### `src/routes/nutrition.py` — New Endpoint
- [x] Add `GET /api/nutrition/weekly-summary?local_date=` endpoint
  - Query NutritionLog grouped by date for the week (Mon–today)
  - Query Workout table for kilojoules per day
  - Compute RMR from profile (or use rmr_override)
  - For each day: budget = rmr_adapted + workout_cal, deficit = budget - intake
  - Compute weekly deficit target from profile goals
  - Return the consolidated summary JSON

#### `src/services/weekly_planner.py`
- [x] Fix Monday miles: always 3mi minimum (line 149)
- [ ] After deploying: regenerate cached plan via `POST /api/weekly-plan/regenerate` (current week's cached plan has 2mi baked in)

### Frontend Changes

#### `src/static/index.html` — NutritionTab
- [x] Add weekly deficit target card (between Daily Budget and progress bars)
  - Show: "Weekly target: -3,500 cal" | "So far: -2,100 cal" | "Remaining: -1,400 cal"
  - Color-code: green if on pace, yellow if behind but recoverable, red if far behind
- [x] Add weekly deficit bar chart (after 7-Day Averages card)
  - Chart.js bar chart, Mon–Sun x-axis
  - Green/red bars based on daily deficit vs. daily target
  - Dashed horizontal line for daily target
  - Custom afterDraw plugin for the target line
- [x] Refactor Recent Entries to group by date
  - Date header row: "Mon Mar 3 — 1,850 cal | 165g protein | -500 cal deficit"
  - Individual entries below each header (existing format + delete button)
  - Deficit color: green if positive (in deficit), red if negative (over budget)
  - Dim the deficit label if budget was RMR-only (no workout data for that day)

#### `src/static/index.html` — MorningBriefing
- [x] Rename "Today's Workout" to "Recovery Check"
- [x] Only render when recovery data suggests modifying the plan
- [x] Show the plan's `recovery_adjustment` text rather than `prescribe_workout()` output

## Layout Order (NutritionTab after changes)

1. Profile banner (if needed)
2. Log Nutrition form
3. **Weekly Deficit Target card** ← NEW
4. Daily Budget Feedback card (existing)
5. Budget Breakdown card (existing)
6. Calories/Protein progress bars (existing)
7. **Weekly Deficit Bar Chart** ← NEW
8. 7-Day Averages card (existing)
9. Weight Trend chart (existing)
10. **Recent Entries grouped by date with deficits** ← MODIFIED

## Edge Cases

| Scenario | Behavior |
|---|---|
| No profile set | Show "Set up your profile" banner, hide deficit features |
| No goal_weight or goal_target_date | Weekly target card: "Set a weight goal and target date in Settings" |
| goal_target_date in past | "Target date has passed — update in Settings" |
| Goal already reached | "Goal reached!" in green |
| Weekly deficit > 7000 cal | Warning about exceeding 2 lbs/week |
| Day with no nutrition logs | No bar in chart, no entry in grouped list |
| Day with no workout data | Use RMR-only budget, mark as approximate |
| weeks_remaining very small | Cap display at 7000 cal/week with warning |
| Whoop not connected | All budgets are RMR-only (still useful) |

## Acceptance Criteria

- [ ] Each past day in Recent Entries shows its calorie deficit (budget - intake)
- [ ] Entries are grouped by date with a daily summary header
- [ ] Weekly deficit target is displayed with safety bounds and graceful fallbacks
- [ ] Bar chart shows Mon–today deficit bars with a target line
- [ ] Bars are green when hitting daily target, red when not
- [ ] Monday in weekly plan always shows 3mi minimum
- [ ] Dashboard has only one "Today's Workout" display (from weekly plan)
- [ ] Briefing shows "Recovery Check" only when recovery warrants adjustment
- [ ] Workout table stores kilojoule data from Whoop sync
- [ ] All features degrade gracefully when data is missing

## Sources & References

- `src/services/coaching.py:418-468` — NutritionPlan, compute_rmr, compute_nutrition_plan
- `src/routes/briefing.py:327-420` — Briefing nutrition target computation
- `src/routes/nutrition.py` — Existing nutrition CRUD
- `src/routes/weekly.py:74-92` — Weekly scorecard nutrition compliance
- `src/services/weekly_planner.py:149` — Monday miles logic
- `src/static/index.html:951-1183` — NutritionTab component
- `src/static/index.html:602-637` — TodayWorkoutCard
- `src/static/index.html:671-730` — MorningBriefing with workout section
