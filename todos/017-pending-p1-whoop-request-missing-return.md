---
status: pending
priority: p1
issue_id: "017"
tags: [code-review, bug, python]
dependencies: []
---

# Runtime Bug: `_request` returns None on retry exhaustion

## Problem Statement

`WhoopClient._request()` has a `for` loop with `max_retries + 1` iterations. If all iterations are consumed by 429 rate-limit retries, the loop exits without returning anything, and the method implicitly returns `None`. Every caller assumes a `dict` is returned (e.g., `_paginate` calls `data.get("records", [])` on the result), which will raise `AttributeError: 'NoneType' object has no attribute 'get'`.

## Findings

- **File:** `src/whoop.py:186-209`
- **Agent:** Python Quality Reviewer (Critical)
- The `for attempt in range(max_retries + 1)` loop has 4 iterations (0-3). If all are 429 retries, no return statement is reached.
- Additionally, `Retry-After` from Whoop can be up to 60 seconds, meaning the worker blocks for potentially 180+ seconds total.

## Proposed Solutions

### Solution A: Add explicit raise after loop
Add `resp.raise_for_status()` or `raise RuntimeError("Max retries exceeded")` after the for loop.

- **Pros:** Simple, explicit failure
- **Cons:** None
- **Effort:** Small
- **Risk:** None

## Acceptance Criteria

- [ ] `_request` never returns `None` -- either returns a dict or raises
- [ ] `Retry-After` sleep is capped at a reasonable maximum (e.g., 10 seconds)
