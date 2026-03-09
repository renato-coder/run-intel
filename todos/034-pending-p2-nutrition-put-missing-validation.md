---
status: complete
priority: p2
issue_id: "034"
tags: [code-review, validation, api, nutrition]
dependencies: []
---

# PUT /api/nutrition Missing Input Validation

## Problem Statement

The PUT /api/nutrition/<id> endpoint (src/routes/nutrition.py:96-124) does not validate input the same way POST does. POST validates:
- calories and protein_grams are integers
- calories >= 0 and protein >= 0

PUT skips all of this — `int(data["calories"])` will throw ValueError on non-numeric input (returning unhelpful 500), and negative values are accepted.

## Findings

- **Location**: `src/routes/nutrition.py:108-113`
- **Evidence**: POST route (lines 49-61) has full validation; PUT route has none
- **Impact**: Inconsistent API behavior, potential for bad data in DB

## Proposed Solutions

### Option A: Extract shared validation helper
- **Pros**: DRY, consistent validation
- **Cons**: Slightly more code
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] PUT validates calories/protein are integers
- [ ] PUT validates calories >= 0, protein >= 0
- [ ] PUT returns 400 with clear error on invalid input

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-09 | Created from code review | Validation inconsistency between POST and PUT |
