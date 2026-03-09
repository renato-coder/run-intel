"""
Withings API client for Run Intel.

Handles OAuth2 authorization, token management, and weight/body composition
data retrieval from the Withings Health API.

Token resolution: Database (provider="withings") → environment variables.
"""

import logging
import os
import time
from datetime import date, datetime, timezone

import requests as http_requests

from config import WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET, WITHINGS_REDIRECT_URI

logger = logging.getLogger(__name__)

AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"

# Measurement type IDs
MEAS_WEIGHT = 1       # kg
MEAS_FAT_RATIO = 6    # %


class WithingsClient:
    """Client for the Withings Health API with automatic token refresh."""

    def __init__(self):
        self.client_id = WITHINGS_CLIENT_ID
        self.client_secret = WITHINGS_CLIENT_SECRET
        self.redirect_uri = WITHINGS_REDIRECT_URI
        self.access_token = None
        self.refresh_token_value = None
        self.token_expiry = 0

        if not self.client_id:
            return

        if not self._load_tokens_from_db():
            self._load_tokens_from_env()

    # ── Auth URL ──────────────────────────────────────────────────────

    def generate_auth_url(self) -> str:
        """Build the Withings OAuth2 authorization URL."""
        import secrets
        import urllib.parse

        self._oauth_state = secrets.token_urlsafe(32)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "user.metrics",
            "state": self._oauth_state,
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    # ── Token exchange ────────────────────────────────────────────────

    def exchange_code(self, code: str) -> dict:
        """Exchange an authorization code for tokens. Must be done within 30s."""
        resp = http_requests.post(TOKEN_URL, data={
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        })
        resp.raise_for_status()
        body = resp.json().get("body", resp.json())
        self._apply_token_data(body)
        self._save_tokens_to_db()
        return body

    def _refresh_token(self) -> None:
        """Use the refresh token to get a new access token."""
        if not self.refresh_token_value:
            raise RuntimeError("No Withings refresh token. Re-authorize.")
        resp = http_requests.post(TOKEN_URL, data={
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token_value,
        })
        resp.raise_for_status()
        body = resp.json().get("body", resp.json())
        self._apply_token_data(body)
        self._save_tokens_to_db()

    # ── Token persistence ─────────────────────────────────────────────

    def has_tokens(self) -> bool:
        return bool(self.access_token)

    def _apply_token_data(self, data: dict) -> None:
        self.access_token = data["access_token"]
        self.refresh_token_value = data.get("refresh_token", self.refresh_token_value)
        self.token_expiry = time.time() + data.get("expires_in", 10800)

    def _load_tokens_from_db(self) -> bool:
        try:
            from database import SessionLocal, Token
            session = SessionLocal()
            try:
                row = (
                    session.query(Token)
                    .filter(Token.provider == "withings")
                    .order_by(Token.id.desc())
                    .first()
                )
                if row:
                    self.access_token = row.access_token
                    self.refresh_token_value = row.refresh_token
                    self.token_expiry = row.expiry
                    return True
            finally:
                session.close()
        except Exception as e:
            logger.debug("Could not load Withings tokens from DB: %s", e)
        return False

    def _load_tokens_from_env(self) -> bool:
        access = os.environ.get("WITHINGS_ACCESS_TOKEN")
        refresh = os.environ.get("WITHINGS_REFRESH_TOKEN")
        if access and refresh:
            self.access_token = access
            self.refresh_token_value = refresh
            self.token_expiry = float(os.environ.get("WITHINGS_TOKEN_EXPIRY", 0))
            return True
        return False

    def _save_tokens_to_db(self) -> None:
        try:
            from database import SessionLocal, Token
            session = SessionLocal()
            try:
                existing = (
                    session.query(Token)
                    .filter(Token.provider == "withings")
                    .first()
                )
                if existing:
                    existing.access_token = self.access_token
                    existing.refresh_token = self.refresh_token_value
                    existing.expiry = self.token_expiry
                else:
                    session.add(Token(
                        access_token=self.access_token,
                        refresh_token=self.refresh_token_value,
                        expiry=self.token_expiry,
                        provider="withings",
                    ))
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.warning("Could not save Withings tokens to DB: %s", e)

    # ── API requests ──────────────────────────────────────────────────

    def _request(self, url: str, data: dict) -> dict:
        """Make an authenticated POST request with auto-refresh."""
        if not self.access_token:
            raise RuntimeError("No Withings access token. Run auth first.")

        # Refresh if token is expired or close to expiry
        if time.time() > self.token_expiry - 60:
            self._refresh_token()

        resp = http_requests.post(
            url,
            data=data,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        result = resp.json()

        # Status 401 = token expired, retry once
        if result.get("status") == 401:
            self._refresh_token()
            resp = http_requests.post(
                url,
                data=data,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            result = resp.json()

        if result.get("status") != 0:
            raise RuntimeError(f"Withings API error: {result}")

        return result.get("body", {})

    # ── Public API ────────────────────────────────────────────────────

    def get_weight_measurements(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch weight and body fat measurements from Withings.

        Returns list of {"date": date, "weight_kg": float, "body_fat_pct": float|None}
        """
        start_ts = int(datetime.combine(start_date, datetime.min.time(),
                                         tzinfo=timezone.utc).timestamp())
        end_ts = int(datetime.combine(end_date, datetime.max.time(),
                                       tzinfo=timezone.utc).timestamp())

        body = self._request(MEASURE_URL, {
            "action": "getmeas",
            "meastypes": f"{MEAS_WEIGHT},{MEAS_FAT_RATIO}",
            "category": 1,  # real measurements only
            "startdate": start_ts,
            "enddate": end_ts,
        })

        results = []
        for grp in body.get("measuregrps", []):
            meas_date = datetime.fromtimestamp(grp["date"], tz=timezone.utc).date()
            weight_kg = None
            body_fat_pct = None

            for m in grp.get("measures", []):
                real_value = m["value"] * (10 ** m["unit"])
                if m["type"] == MEAS_WEIGHT:
                    weight_kg = round(real_value, 3)
                elif m["type"] == MEAS_FAT_RATIO:
                    body_fat_pct = round(real_value, 1)

            if weight_kg is not None:
                results.append({
                    "date": meas_date,
                    "weight_kg": weight_kg,
                    "body_fat_pct": body_fat_pct,
                })

        return results
