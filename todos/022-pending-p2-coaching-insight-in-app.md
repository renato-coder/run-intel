---
status: pending
priority: p2
issue_id: "022"
tags: [code-review, architecture, simplicity]
dependencies: []
---

# `generate_coaching_insight` -- 90-Line Domain Logic in Routing Module

## Problem Statement

`generate_coaching_insight` is a 90-line function in `app.py` that contains complex domain logic (cardiac drift detection, pace adaptation, recovery-based recommendations). It duplicates analysis patterns from `briefing.py` and could give contradictory advice. It should be extracted and potentially consolidated with the briefing engine.

## Findings

- **File:** `src/app.py:210-302`
- **Agents:** Architecture Strategist, Python Quality Reviewer (Important), Code Simplicity Reviewer
- Contains its own DB session, recovery thresholds, and pace recommendation logic.
- `briefing.py` has similar recovery/HRV analysis with different thresholds.
- Two systems can give contradictory advice (briefing says "rest", coaching says "push pace").

## Proposed Solutions

### Solution A: Extract to own module and reuse briefing status
Move to `coaching.py`. Use the briefing engine's status determination to inform coaching recommendations, creating a single source of truth.

- **Pros:** Single source of coaching truth, shorter app.py, testable
- **Cons:** Requires designing the interface between briefing and coaching
- **Effort:** Medium
- **Risk:** Low

### Solution B: Simplify to use briefing output directly
When logging a run, call `generate_briefing` and include its `play` text as the coaching insight. Remove the separate coaching engine entirely.

- **Pros:** ~90 LOC removed, no contradictions possible
- **Cons:** Loses per-run pace comparison analysis
- **Effort:** Small
- **Risk:** Medium (loses specific coaching features)

## Acceptance Criteria

- [ ] Domain logic is not in `app.py`
- [ ] Coaching and briefing advice never contradict each other
