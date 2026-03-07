---
status: pending
priority: p2
issue_id: "026"
tags: [code-review, security, performance]
dependencies: []
---

# Rate Limiting Only on Login -- No Protection on API Endpoints

## Problem Statement

Rate limiting is applied only to `POST /login` (5/min). API endpoints have no rate limits, allowing database flooding via `POST /api/runs` and Whoop API quota exhaustion via repeated calls to `/api/briefing` or `/api/recovery/today`.

## Findings

- **File:** `src/app.py:48,121`
- **Agents:** Security Sentinel (Medium), Performance Oracle
- `POST /api/runs` can be called unlimited times by an authenticated user.
- GET endpoints that trigger Whoop API calls have no throttling.
- Rate limiter uses `memory://` storage which doesn't persist across worker restarts.

## Proposed Solutions

### Solution A: Add per-endpoint rate limits
Add `@limiter.limit()` to `POST /api/runs` (e.g., 10/min) and Whoop-calling GET endpoints (e.g., 30/min).

- **Pros:** Prevents abuse and accidental API exhaustion
- **Cons:** Could interfere with legitimate rapid usage (unlikely for personal app)
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `POST /api/runs` has a rate limit
- [ ] Whoop-triggering endpoints have rate limits
