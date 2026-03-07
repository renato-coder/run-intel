---
status: pending
priority: p2
issue_id: "023"
tags: [code-review, security]
dependencies: []
---

# Missing Content-Security-Policy Header and SRI Hashes on CDN Scripts

## Problem Statement

Security headers omit `Content-Security-Policy`. Four CDN scripts (React, ReactDOM, Babel, Chart.js) lack Subresource Integrity hashes. A CDN compromise or DNS hijack would allow arbitrary JavaScript execution in the authenticated user's session.

## Findings

- **Files:** `src/app.py:56-63` (headers), `src/static/index.html:10-13` (script tags)
- **Agent:** Security Sentinel (Medium)
- `crossorigin="anonymous"` is already set (prerequisite for SRI).
- In-browser Babel requires `'unsafe-inline'` in CSP, weakening protection.

## Proposed Solutions

### Solution A: Add SRI hashes + CSP header
1. Compute `integrity="sha384-..."` for each CDN script and add to tags.
2. Add CSP header: `default-src 'self'; script-src 'self' https://unpkg.com https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src https://fonts.gstatic.com; connect-src 'self'`

- **Pros:** Prevents CDN supply-chain attacks, limits XSS impact
- **Cons:** `'unsafe-inline'` still needed for Babel; SRI hashes must be updated on version bumps
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] All CDN `<script>` tags have `integrity` attributes
- [ ] CSP header is set on all responses
