---
status: complete
priority: p1
issue_id: "001"
tags: [code-review, security]
dependencies: []
---

# Hardcoded Secrets, Default Password, and Debug Mode

## Problem Statement

The application has multiple critical security issues around secret management that would allow unauthorized access if deployed without careful environment configuration.

## Findings

### 1. Hardcoded default password (CRITICAL)
- **File:** `src/app.py:31`
- **Code:** `APP_PASSWORD = os.environ.get("APP_PASSWORD", "runintel2026")`
- **Risk:** If `APP_PASSWORD` env var is not set, the app is accessible with a publicly known credential committed to the repository.
- **Agents:** Security Sentinel, Data Integrity Guardian, Architecture Strategist, Python Reviewer

### 2. Flask debug=True hardcoded (CRITICAL)
- **File:** `src/app.py:742`
- **Code:** `app.run(host="0.0.0.0", port=port, debug=True)`
- **Risk:** Debug mode exposes the Werkzeug interactive debugger, enabling remote code execution. Anyone starting the app via `python src/app.py` gets full RCE on 0.0.0.0.
- **Agent:** Security Sentinel

### 3. SESSION_SECRET regenerates on restart
- **File:** `src/app.py:35`
- **Code:** `_SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))`
- **Risk:** Every restart invalidates all sessions. `app.secret_key` (line 39) is always random, never from config.
- **Agents:** Security Sentinel, Architecture Strategist

### 4. Empty DATABASE_URL fallback
- **File:** `src/database.py:15`
- **Code:** `DATABASE_URL = os.environ.get("DATABASE_URL", "")`
- **Risk:** Crashes with cryptic error instead of clear message at startup.
- **Agents:** Data Integrity Guardian, Python Reviewer

## Proposed Solutions

### Option A: Fail-fast on missing config (Recommended)
- Remove all default values for secrets
- Crash at startup with clear error messages if required env vars are missing
- Gate debug mode on FLASK_DEBUG env var
- **Pros:** Simple, secure, explicit
- **Cons:** Slightly harder first-time setup
- **Effort:** Small
- **Risk:** Low

### Option B: Centralized config.py module
- Create `src/config.py` that validates all env vars at import time
- Single `load_dotenv()` call (currently only in whoop.py)
- All modules import from config instead of reading env directly
- **Pros:** Clean separation, single source of truth
- **Cons:** More refactoring
- **Effort:** Medium
- **Risk:** Low

## Recommended Action

(To be filled during triage)

## Technical Details

**Affected files:** `src/app.py`, `src/database.py`, `src/whoop.py`
**Components:** Authentication, configuration, startup

## Acceptance Criteria

- [ ] No hardcoded default password in source code
- [ ] App fails at startup if APP_PASSWORD not set
- [ ] Debug mode is off by default, configurable via env var
- [ ] SESSION_SECRET and app.secret_key derived from persistent env var
- [ ] DATABASE_URL missing produces clear error message
- [ ] All required env vars validated at startup

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | Multiple agents flagged independently |

## Resources

- Flask debug mode security: https://flask.palletsprojects.com/en/3.0.x/debugging/
- OWASP Hardcoded Credentials: https://owasp.org/www-community/vulnerabilities/Use_of_hard-coded_password
