---
status: pending
priority: p2
issue_id: "020"
tags: [code-review, performance]
dependencies: []
---

# Duplicate Whoop API Calls on Every Page Load -- No Cache

## Problem Statement

Every page load triggers 6 parallel API calls from the frontend. Two of these (`/api/briefing` and `/api/recovery/today`) independently call the Whoop API for the same recovery data, creating redundant external API calls. There is no caching layer, so the Whoop API is hit on every single page load/refresh, risking rate limits and causing slow responses.

## Findings

- **Files:** `src/app.py:313-349` (briefing), `src/app.py:371-377` (recovery/today)
- **Agents:** Performance Oracle (Critical), Architecture Strategist, Code Simplicity Reviewer
- Both endpoints call `fetch_and_cache_recovery(session)` which creates a new `WhoopClient()` and hits the Whoop API.
- A `WhoopClient()` constructor itself queries the DB for tokens each time.
- Rate-limited responses trigger `time.sleep(60)` which blocks the worker.

## Proposed Solutions

### Solution A: In-memory cache with TTL
Cache the Whoop recovery response at module level with a 5-minute TTL. A simple dict with a timestamp suffices for a single-user app.

- **Pros:** Eliminates duplicate API calls, prevents rate limiting, fast page loads
- **Cons:** Slightly stale data (max 5 min)
- **Effort:** Small
- **Risk:** Low

### Solution B: Consolidate into single `/api/dashboard` endpoint
Return all dashboard data from a single endpoint, making one Whoop call that feeds both recovery and briefing.

- **Pros:** 6 HTTP calls -> 1, single Whoop call, single DB session
- **Cons:** Larger refactor, all-or-nothing loading on frontend
- **Effort:** Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] Whoop API is called at most once per 5 minutes for recovery data
- [ ] Page loads do not trigger redundant Whoop API calls
