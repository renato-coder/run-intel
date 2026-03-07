---
status: pending
priority: p2
issue_id: "024"
tags: [code-review, performance, api]
dependencies: []
---

# Unbounded Query Results on `/api/runs` and `/api/trends`

## Problem Statement

`GET /api/runs` and `GET /api/trends` return all matching records with no pagination or limit. The frontend only displays 20 runs (`runs.slice(0, 20)`), meaning 80%+ of transferred data is unused. As the database grows over years, these payloads will become increasingly large.

## Findings

- **Files:** `src/app.py:352-368` (runs), `src/app.py:396-416` (trends)
- **Agents:** Performance Oracle (Opt-3/4), Security Sentinel (Medium), Architecture Strategist
- `/api/runs` returns every run ever logged; frontend shows only 20.
- `/api/trends` has no date filter (unlike snapshot which uses 30d).

## Proposed Solutions

### Solution A: Add LIMIT to queries + optional pagination params
Add `.limit(50)` default to `/api/runs` and a 90-day default filter to `/api/trends`. Accept optional `limit`/`offset` query params.

- **Pros:** Reduces payload size, prevents memory issues at scale
- **Cons:** Frontend may need adjustment if it relies on full data
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `/api/runs` returns at most 50 records by default
- [ ] `/api/trends` filters to last 90 days by default
- [ ] Both accept optional `limit`/`offset` or `days` query parameters
