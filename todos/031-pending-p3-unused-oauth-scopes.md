---
status: pending
priority: p3
issue_id: "031"
tags: [code-review, security, simplicity]
dependencies: []
---

# OAuth Scopes Request More Permissions Than Needed

## Problem Statement

The Whoop OAuth scopes request `read:cycles`, `read:sleep`, and `read:body_measurement` which are never used by the application. Requesting minimum necessary permissions is a security best practice.

## Findings

- **File:** `src/whoop.py:31`
- **Agent:** Code Simplicity Reviewer
- App only uses: `read:recovery`, `read:workout`, `read:profile`, `offline`
- 3 unused scopes: `read:cycles`, `read:sleep`, `read:body_measurement`

## Proposed Solutions

### Solution A: Remove unused scopes
Change SCOPES to only include what's needed. Note: requires re-authorization.

- **Pros:** Minimal permissions, cleaner consent screen
- **Cons:** Requires user to re-run `auth.py`
- **Effort:** Small
- **Risk:** Low (but requires re-auth)

## Acceptance Criteria

- [ ] SCOPES only contains scopes the app actually uses
