---
status: pending
priority: p2
issue_id: "025"
tags: [code-review, security, api]
dependencies: []
---

# Shoe Input Not Validated + Run IDs Not Exposed in API

## Problem Statement

The `shoe` field on `POST /api/runs` accepts arbitrary strings with no length limit or allowlist validation. Additionally, `to_dict()` excludes the `id` field, making runs unreferenceable by API clients.

## Findings

- **File:** `src/app.py:478` (shoe validation), `src/database.py:36-37` (id skip)
- **Agents:** Security Sentinel (Medium -- shoe), Agent-Native Reviewer (Warning -- run IDs)
- The `shoe` column is `Text` (unbounded). An attacker could submit arbitrarily long strings.
- Run IDs are excluded from API responses, so clients cannot reference specific runs.

## Proposed Solutions

### Solution A: Validate shoe + expose IDs
1. Validate `shoe` against known keys or enforce max length (50 chars).
2. Include `id` in `to_dict()` output.

- **Pros:** Prevents data pollution, enables future CRUD operations on runs
- **Cons:** Minor breaking change if anything depends on id-less responses
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `POST /api/runs` rejects shoe values longer than 50 characters
- [ ] Run IDs are included in API responses
