---
status: complete
priority: p3
issue_id: "039"
tags: [code-review, duplication, validation]
dependencies: []
---

# Duplicated Date Backdating Validation

## Problem Statement

The date validation + backdating logic (parse ISO date, reject future dates, reject > 7 days back) is copy-pasted between nutrition.py (lines 65-74) and body_comp.py (lines 64-74). Should be extracted to a shared helper.

## Findings

- **Location**: `src/routes/nutrition.py:65-74` and `src/routes/body_comp.py:64-74`
- **Evidence**: Identical 10-line blocks

## Proposed Solutions

### Option A: Extract to shared validation helper
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] Date validation extracted to shared function
- [ ] Both routes use the shared helper

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-09 | Created from code review | DRY principle |
