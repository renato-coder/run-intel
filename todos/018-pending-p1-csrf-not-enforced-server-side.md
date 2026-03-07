---
status: pending
priority: p1
issue_id: "018"
tags: [code-review, security]
dependencies: []
---

# CSRF Protection Sent But Never Checked Server-Side

## Problem Statement

The frontend sends `X-Requested-With: RunIntel` on every API call, but no server-side code validates this header. The `POST /api/runs` endpoint is vulnerable to cross-site request forgery. An attacker who tricks the user into visiting a malicious page could submit arbitrary runs.

## Findings

- **File:** `src/static/index.html:365` (header sent)
- **File:** `src/app.py` (no validation anywhere)
- **Agents:** Security Sentinel (High), Code Simplicity Reviewer (YAGNI -- sent but never checked)
- `SameSite=Lax` provides partial mitigation but is not sufficient defense-in-depth.

## Proposed Solutions

### Solution A: Add `@app.before_request` check on `/api/*` POST routes
Reject requests to state-changing API endpoints that lack the `X-Requested-With: RunIntel` header with a 403.

- **Pros:** Simple, completes the existing pattern
- **Cons:** Breaks any future non-browser API clients that don't send the header
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `POST /api/runs` returns 403 if `X-Requested-With` header is missing
- [ ] GET endpoints remain unaffected
