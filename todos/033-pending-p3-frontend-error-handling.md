---
status: complete
priority: p3
issue_id: "033"
tags: [code-review, quality, frontend]
dependencies: []
---

# Frontend API Calls Have No Error Handling

## Problem Statement

All 6 API calls in `loadAll()` use `.then()` with no `.catch()`. If any endpoint fails (rate limiting, timeout, server error), the error is silently swallowed and the component never updates. The user sees no feedback.

## Findings

- **File:** `src/static/index.html:787-793`
- **Agents:** Performance Oracle (Opt-9)
- `api('/api/runs').then(setRuns)` -- no catch
- Same for all 5 other calls
- Chart.js `TrendChart` destroys/recreates on every update instead of using `chart.update()`

## Proposed Solutions

### Solution A: Add .catch() handlers and loading/error states
Add `.catch(console.error)` at minimum. Optionally add a global error state.

- **Pros:** Visible error feedback, debuggable
- **Cons:** Minor frontend changes
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] All API calls in `loadAll` have `.catch()` handlers
- [ ] Errors are surfaced to the user or at minimum logged to console
