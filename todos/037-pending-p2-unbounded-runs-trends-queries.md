---
status: complete
priority: p2
issue_id: "037"
tags: [code-review, performance, api, pagination]
dependencies: []
---

# Unbounded GET /api/runs and GET /api/trends

## Problem Statement

GET /api/runs (src/routes/runs.py:118-133) and GET /api/trends (src/routes/runs.py:245-264) return ALL records from the database with no limit or pagination. As run history grows, response sizes and query times will increase linearly.

## Findings

- **Location**: `src/routes/runs.py:121-127` (runs) and `src/routes/runs.py:248-253` (trends)
- **Evidence**: No `.limit()` or date filter on either query
- **Impact**: Degrading performance over time; large JSON responses

## Proposed Solutions

### Option A: Add ?days= filter (consistent with nutrition/body_comp)
- **Pros**: Simple, consistent with other endpoints
- **Cons**: May not cover all use cases
- **Effort**: Small
- **Risk**: Low — backwards compatible if default is large enough

## Acceptance Criteria

- [ ] GET /api/runs supports ?days= filter (default 90)
- [ ] GET /api/trends supports ?days= filter (default 90)
- [ ] Response sizes are bounded

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-09 | Created from code review | Already tracked in todo #024, confirming still applicable |
