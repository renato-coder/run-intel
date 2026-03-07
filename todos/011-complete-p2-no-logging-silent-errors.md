---
status: complete
priority: p2
issue_id: "011"
tags: [code-review, quality]
dependencies: []
---

# No Structured Logging, Silent Error Swallowing

## Problem Statement

All diagnostics use `print()` (78 occurrences). Eight `except Exception` blocks catch everything and either `pass` or print, making failures invisible in production.

## Findings

### 1. No logging module used (HIGH)
- Zero files import `logging`
- 78 `print()` calls with no log levels, no structured output
- Background refresh errors indistinguishable from normal output
- **Agents:** Python Reviewer, Architecture Strategist

### 2. Silent exception swallowing (HIGH)
- **File:** `src/whoop.py:124` - `except Exception: pass` on token file write
- **File:** `src/whoop.py:141` - `except Exception: pass` on token DB load
- **File:** `src/app.py:338,457,588,595,707` - broad catches with print
- Token persistence failures are completely invisible
- **Agents:** Python Reviewer, Security Sentinel, Architecture Strategist

## Proposed Solutions

### Option A: Replace print with logging, narrow exceptions (Recommended)
- Add `import logging; logger = logging.getLogger(__name__)` to each module
- Replace `print()` with appropriate log levels
- Narrow `except Exception` to specific types (RequestError, OSError, SQLAlchemyError)
- Never use bare `except Exception: pass`
- **Effort:** Small-Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] All modules use Python `logging` module
- [ ] Zero `print()` calls in production code paths
- [ ] No bare `except Exception: pass` anywhere
- [ ] Exception handlers catch specific exception types
- [ ] Logging configured with appropriate levels in Flask app

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
