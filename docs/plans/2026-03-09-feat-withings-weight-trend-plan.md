---
title: "feat: Withings weight trend on Nutrition tab"
type: feat
status: active
date: 2026-03-09
---

# Withings Weight Trend on Nutrition Tab

## Overview

Connect to the Withings API to automatically pull weight measurements from the user's smart scale, and display a trended weight line chart on the Nutrition tab. This replaces manual weight logging as the primary data source and gives immediate visual feedback on whether the calorie budget is working.

## Problem Statement

Weight is currently logged manually via the Body Comp tab. The user has a Withings smart scale that automatically records weight, but this data isn't flowing into the app. The Nutrition tab — where the user checks their daily budget — has no weight context. Showing a weight trend right next to the calorie data closes the feedback loop: "Am I eating the right amount? Is my weight actually moving?"

## New Model

```
Withings Scale → API → BodyComp table (source="withings")
                                ↓
              Nutrition Tab: weight trend chart (last 30 days)
              Body Comp Tab: existing chart (now includes Withings data)
```

## Key Decisions

1. **Use the Withings REST API directly** (not the `withings-api` PyPI package). The package hasn't been updated since 2022. The API is simple enough — one POST endpoint for measurements. Follow the same pattern as `src/whoop.py`.
2. **OAuth via CLI script** (same as Whoop). No web callback route needed. User runs `python3 src/auth_withings.py`, pastes the redirect URL, tokens are saved.
3. **Store tokens in the same `Token` table** but add a `provider` column (`"whoop"` or `"withings"`). Single-row-per-provider upsert pattern.
4. **Sync weights into the existing `BodyComp` table.** Add a `source` column (`"manual"` default, `"withings"` for synced data) so we don't duplicate or overwrite manual entries.
5. **Sync on briefing load** — when the Nutrition tab loads (which calls `/api/briefing`), also sync recent Withings weights. Lazy, no background jobs, same pattern as Whoop recovery/workout fetching.
6. **Weight trend chart on Nutrition tab** — reuse the `BioTrendChart` component (already used for RHR/HRV trends on Longevity tab). Show last 30 days of weight, green line, lower-is-better (during a cut).
7. **Withings env vars are optional.** If not set, Withings features are simply hidden. The app should not crash or require Withings to function.
8. **Convert kg to lbs on sync.** Withings returns weight in kg. The app uses lbs everywhere. Convert: `lbs = kg * 2.20462`.
9. **Deduplicate on sync.** Before inserting, check if a BodyComp entry with the same date and source="withings" already exists. Skip if so.
10. **Withings redirect URI:** `https://run-intel-production-b7ec.up.railway.app/api/withings/callback` — Withings requires HTTPS, no localhost. We'll add a minimal callback route just for the OAuth exchange.

## Technical Approach

### Backend Changes

**`src/config.py`** — Add optional Withings env vars:

```python
WITHINGS_CLIENT_ID = os.environ.get("WITHINGS_CLIENT_ID")
WITHINGS_CLIENT_SECRET = os.environ.get("WITHINGS_CLIENT_SECRET")
WITHINGS_REDIRECT_URI = os.environ.get("WITHINGS_REDIRECT_URI", "")
```

**`src/database.py`** — Schema changes:

- Add `provider` column to `Token` table: `VARCHAR(20)`, default `"whoop"`
- Add `source` column to `BodyComp` table: `VARCHAR(20)`, default `"manual"`
- Migration SQL (idempotent):
  ```sql
  ALTER TABLE tokens ADD COLUMN IF NOT EXISTS provider VARCHAR(20) DEFAULT 'whoop';
  ALTER TABLE body_comp ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'manual';
  ```

**`src/withings.py`** (new) — Withings API client:

```python
class WithingsClient:
    AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
    TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
    MEASURE_URL = "https://wbsapi.withings.net/measure"

    def __init__(self):
        # Load tokens from DB (provider="withings") or env
        ...

    def generate_auth_url(self) -> str:
        # scope=user.metrics, response_type=code
        ...

    def exchange_code(self, code: str) -> dict:
        # POST to TOKEN_URL with action=requesttoken, grant_type=authorization_code
        # 30-second window to exchange!
        ...

    def refresh_token(self) -> None:
        # POST with action=requesttoken, grant_type=refresh_token
        ...

    def get_weight_measurements(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch weight + body fat from Withings.

        POST to MEASURE_URL with:
          action=getmeas
          meastypes=1,6  (1=weight_kg, 6=fat_ratio_pct)
          category=1 (real measurements only)
          startdate=unix_ts, enddate=unix_ts

        Returns list of {"date": date, "weight_kg": float, "body_fat_pct": float|None}
        """
        # Parse measuregrps: real_value = value * 10^unit
        ...
```

**`src/auth_withings.py`** (new) — CLI OAuth script (same pattern as `src/auth.py`):

```python
# Print auth URL, user opens in browser, pastes redirect URL
# Extract code from URL, call client.exchange_code(code)
# Tokens saved to DB
```

**`src/routes/withings.py`** (new) — OAuth callback + sync:

```python
bp = Blueprint("withings", __name__)

@bp.route("/api/withings/callback")
def withings_callback():
    """OAuth callback — exchange code for tokens."""
    code = request.args.get("code")
    client = WithingsClient()
    client.exchange_code(code)
    return "Withings connected! You can close this tab."

@bp.route("/api/withings/status")
def withings_status():
    """Check if Withings is connected."""
    # Check if valid tokens exist for provider="withings"
    ...
```

**`src/routes/briefing.py`** — Add Withings weight sync:

```python
def _sync_withings_weights(session):
    """Sync last 30 days of Withings weight data into BodyComp table."""
    from withings import WithingsClient
    try:
        client = WithingsClient()
        if not client.has_tokens():
            return
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=30)
        measurements = client.get_weight_measurements(start, today)
        for m in measurements:
            # Check for existing entry (same date + source=withings)
            existing = session.query(BodyComp).filter(
                BodyComp.date == m["date"],
                BodyComp.source == "withings",
            ).first()
            if existing:
                existing.weight_lbs = round(m["weight_kg"] * 2.20462, 1)
                if m.get("body_fat_pct"):
                    existing.body_fat_pct = m["body_fat_pct"]
            else:
                session.add(BodyComp(
                    date=m["date"],
                    weight_lbs=round(m["weight_kg"] * 2.20462, 1),
                    body_fat_pct=m.get("body_fat_pct"),
                    source="withings",
                ))
        session.flush()
    except Exception:
        logger.exception("Error syncing Withings weights")
```

Add `_sync_withings_weights(session)` call inside `get_briefing()`, after recovery fetch.

Add weight trend data to the briefing response:

```python
# Weight trend (last 30 days from BodyComp)
weight_entries = (
    session.query(BodyComp.date, BodyComp.weight_lbs)
    .filter(BodyComp.date >= cutoff_30d)
    .order_by(BodyComp.date)
    .all()
)
result["weight_trend"] = [
    {"date": w.date.isoformat(), "value": round(float(w.weight_lbs), 1)}
    for w in weight_entries
]
```

### Frontend Changes

**`src/static/index.html` — NutritionTab:**

Add a weight trend chart between the progress bars and 7-day averages, using the existing `BioTrendChart` component:

```jsx
{/* Weight trend (from Withings or manual) */}
{briefing?.weight_trend?.length >= 2 && (
  <div className="card" style={{ marginTop: 16 }}>
    <div className="card-header"><h2>WEIGHT TREND</h2></div>
    <BioTrendChart
      data={briefing.weight_trend}
      label="Weight"
      color="#00F19F"
      unit=" lbs"
      lowerIsBetter={true}
    />
  </div>
)}
```

**`src/static/index.html` — SettingsTab:**

Add a "Connect Withings" button (or "Connected" status):

```jsx
<h3>Integrations</h3>
{withingsConnected ? (
  <div className="dim">Withings scale: Connected</div>
) : (
  <a href="/api/withings/auth" className="btn btn-sm">Connect Withings Scale</a>
)}
```

## Files to Modify

| File | Changes |
|------|---------|
| `src/config.py` | Add optional `WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`, `WITHINGS_REDIRECT_URI` |
| `src/database.py` | Add `provider` to Token, `source` to BodyComp, migration SQL |
| `src/withings.py` (new) | `WithingsClient` class — OAuth + weight measurements |
| `src/auth_withings.py` (new) | CLI script for initial OAuth flow |
| `src/routes/withings.py` (new) | OAuth callback route, connection status |
| `src/routes/__init__.py` | Register withings blueprint |
| `src/routes/briefing.py` | Sync Withings weights, add `weight_trend` to response |
| `src/static/index.html` | Weight trend chart on NutritionTab, Withings status on SettingsTab |
| `requirements.txt` | No new dependencies (uses `requests` already available) |

## Environment Variables (Railway)

```bash
railway variables set WITHINGS_CLIENT_ID=aa5efc529ef0cf1ca8dd95627dc20442b6d37034e91f5dc168d0a3f83631a06d
railway variables set WITHINGS_CLIENT_SECRET=93064219e34c9c6a9341a2e31f67e5ced382b544279bd32c9a600ccbea4b4c31
railway variables set WITHINGS_REDIRECT_URI=https://run-intel-production-b7ec.up.railway.app/api/withings/callback
```

## Acceptance Criteria

- [ ] `WithingsClient` class handles OAuth2 (auth URL, code exchange, token refresh)
- [ ] Tokens stored in DB with `provider="withings"`, auto-refresh on expiry
- [ ] `get_weight_measurements()` fetches weight (type 1) and fat ratio (type 6)
- [ ] Withings weights synced to `BodyComp` table with `source="withings"` on each briefing load
- [ ] Deduplication: same date + source doesn't create duplicates
- [ ] kg→lbs conversion: `weight_kg * 2.20462`
- [ ] Value decoding: `real_value = value * 10^unit` (Withings scientific notation)
- [ ] Nutrition tab shows 30-day weight trend line chart (reuses `BioTrendChart`)
- [ ] Chart shows "lower is better" trend indicator (for active cut)
- [ ] Settings tab shows Withings connection status
- [ ] App works normally when Withings env vars are not set (graceful degradation)
- [ ] OAuth callback route at `/api/withings/callback` handles code exchange
- [ ] CLI auth script (`auth_withings.py`) works for initial token setup
- [ ] Withings API errors don't break the briefing response

## Recommended Build Order

1. **Schema + config** — Add env vars, Token.provider, BodyComp.source columns
2. **WithingsClient** — OAuth + measurement fetching (test with CLI auth script)
3. **Sync + briefing** — Wire up sync in briefing route, add weight_trend to response
4. **Frontend** — Weight trend chart on Nutrition tab, connection status on Settings
5. **Deploy + auth** — Set Railway env vars, run OAuth flow, verify data flows
