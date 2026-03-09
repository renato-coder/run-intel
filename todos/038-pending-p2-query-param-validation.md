---
status: complete
priority: p2
issue_id: "038"
tags: [code-review, validation, api]
dependencies: []
---

# Query Parameter Validation Missing

## Problem Statement

Several endpoints use `int(request.args.get("days", 30))` without try/except. If a user passes `?days=abc`, this throws ValueError caught only by the generic 500 error handler — returning an unhelpful "Internal server error" instead of a 400 validation error.

## Findings

- **Location**: `src/routes/nutrition.py:16`, `src/routes/body_comp.py:16`
- **Evidence**: `days = int(request.args.get("days", 30))` — no validation
- **Impact**: Non-numeric query params return 500 instead of 400

## Proposed Solutions

### Option A: Wrap in try/except with 400 response
- **Pros**: Clear error messages
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] Non-numeric `days` param returns 400 with clear error
- [ ] Negative `days` param returns 400

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-09 | Created from code review | |
