---
status: pending
priority: p1
issue_id: "019"
tags: [code-review, architecture, api]
dependencies: []
---

# Auth Decorator Returns 302 Redirect Instead of 401 for API Routes

## Problem Statement

The `require_auth` decorator returns `redirect("/login")` for all unauthenticated requests, including `/api/*` endpoints. Programmatic clients receive a 302 redirect to an HTML page instead of a 401 JSON error. This also blocks Bearer token auth, making the API inaccessible to agents/scripts.

## Findings

- **File:** `src/app.py:109-117`
- **Agents:** Agent-Native Reviewer (Critical), Architecture Strategist
- A programmatic client gets a 302 with no useful body, or follows the redirect and gets HTML when expecting JSON.
- No `Authorization: Bearer <token>` support exists.

## Proposed Solutions

### Solution A: Detect API paths and return 401 JSON + add Bearer token support
In `require_auth`, check if the path starts with `/api/`. If so, also check `Authorization: Bearer <token>` header. If neither cookie nor header auth succeeds, return `jsonify({"error": "Authentication required"}), 401`.

- **Pros:** Makes all API endpoints programmatically accessible; backwards-compatible
- **Cons:** Slightly more complex decorator
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `/api/*` routes return 401 JSON when unauthenticated (not 302)
- [ ] `Authorization: Bearer <AUTH_TOKEN>` header is accepted as an auth alternative
- [ ] Cookie-based auth continues to work for the SPA
