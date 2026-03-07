---
status: complete
priority: p2
issue_id: "006"
tags: [code-review, security]
dependencies: ["001"]
---

# Weak Session Management and Plaintext Token Storage

## Problem Statement

A single static auth token is shared across all sessions with no revocation mechanism, and OAuth tokens are stored in plaintext in both the database and a JSON file.

## Findings

### 1. Static shared auth token (HIGH)
- **File:** `src/app.py:35-36`
- One deterministic `AUTH_TOKEN` computed at startup, shared by all sessions
- No per-session tokens, no revocation, no rotation
- Token leak grants 30-day access with no way to invalidate
- **Agent:** Security Sentinel

### 2. OAuth tokens stored in plaintext (HIGH)
- **Files:** `src/database.py:85-91`, `src/whoop.py:116-125`
- Access and refresh tokens stored as plain Text columns in DB
- Also written as plaintext JSON to `data/tokens.json` with default permissions
- Tokens stored in 3 redundant locations (DB, file, env vars) expanding attack surface
- **Agents:** Security Sentinel, Data Integrity Guardian

## Proposed Solutions

### Option A: Per-session tokens + encrypt OAuth tokens
- Generate unique session tokens stored server-side (DB or signed cookies)
- Encrypt OAuth tokens at rest using `cryptography.fernet`
- Eliminate file-based token storage
- **Effort:** Medium
- **Risk:** Low

### Option B: Minimal improvements
- Keep HMAC auth token but make it rotate on password change
- Set file permissions on tokens.json to 0o600
- **Effort:** Small
- **Risk:** Medium (doesn't fully address the issues)

## Acceptance Criteria

- [ ] Auth tokens are unique per session or properly signed
- [ ] OAuth tokens encrypted at rest in database
- [ ] File-based token storage eliminated or encrypted
- [ ] Token file has restrictive permissions if kept

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
