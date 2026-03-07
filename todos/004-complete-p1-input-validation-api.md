---
status: complete
priority: p1
issue_id: "004"
tags: [code-review, security]
dependencies: []
---

# No Input Validation on POST /api/runs

## Problem Statement

The run logging API endpoint performs zero validation on user input, allowing crashes, data corruption, and potential denial of service.

## Findings

- **File:** `src/app.py:569-571`
- `float(data["distance_miles"])` crashes with KeyError or ValueError on bad input
- Zero distance causes ZeroDivisionError in `format_pace()` at line 574
- Negative values, NaN, Infinity are accepted and stored in DB
- Missing Content-Type check (`get_json()` returns None for non-JSON)
- No shoe value validation (API accepts any string, frontend constrains to dropdown)
- **Agents:** Security Sentinel, Data Integrity Guardian

## Proposed Solutions

### Option A: Inline validation (Recommended)
- Validate types, ranges, and required fields before processing
- Return 400 with clear error message on invalid input
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] Missing or non-numeric distance/time returns 400
- [ ] Zero or negative distance/time returns 400
- [ ] Unreasonable values (distance > 200, time > 2000) returns 400
- [ ] Non-JSON Content-Type returns 400
- [ ] Invalid shoe value handled gracefully

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
