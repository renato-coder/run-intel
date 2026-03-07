---
status: complete
priority: p2
issue_id: "005"
tags: [code-review, security]
dependencies: []
---

# Missing Web Security: CSRF, Security Headers, SRI

## Problem Statement

The application lacks CSRF protection, HTTP security headers, and Subresource Integrity on CDN scripts, leaving it vulnerable to cross-site attacks and supply chain compromise.

## Findings

### 1. No CSRF protection (HIGH)
- **File:** `src/app.py:94-108, 565-661`
- Cookie-based auth with no CSRF tokens on POST endpoints
- SameSite=Lax provides partial mitigation but not complete
- **Agent:** Security Sentinel

### 2. No security headers (MEDIUM)
- **File:** `src/app.py` (no after_request handler)
- Missing: CSP, X-Content-Type-Options, X-Frame-Options, HSTS, Referrer-Policy
- **Agent:** Security Sentinel

### 3. CDN scripts without SRI hashes (MEDIUM)
- **File:** `src/static/index.html:9-12`
- React, ReactDOM, Babel, Chart.js loaded from unpkg/jsdelivr without integrity attributes
- CDN compromise = arbitrary JS execution in authenticated context
- **Agent:** Security Sentinel

## Proposed Solutions

### Option A: Add security headers + SRI (Recommended)
- Add `after_request` handler with security headers
- Add `integrity` and `crossorigin` attributes to all CDN script tags
- For CSRF: require custom `X-Requested-With` header on JSON API calls
- **Effort:** Small
- **Risk:** Low

### Option B: Full Flask-WTF integration
- Install Flask-WTF for CSRF token management
- **Effort:** Medium (more invasive)
- **Risk:** Low

## Acceptance Criteria

- [ ] Security headers set on all responses (CSP, X-Frame-Options, HSTS, etc.)
- [ ] SRI hashes on all CDN script tags
- [ ] CSRF mitigation on state-changing endpoints
- [ ] CDN versions pinned to exact semver

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
