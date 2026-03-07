"""
Whoop API client for Run Intel.

Handles OAuth2 authorization, token management, and all API calls
to the Whoop developer API (v2).

Token resolution order:
  1. Database (tokens table)
  2. Environment variables (WHOOP_ACCESS_TOKEN, WHOOP_REFRESH_TOKEN, WHOOP_TOKEN_EXPIRY)
  3. Local file (data/tokens.json)

On refresh, new tokens are saved to the database and file.
"""

import json
import logging
import os
import secrets
import time
import urllib.parse

import requests as http_requests

from config import TOKEN_PATH, WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, WHOOP_REDIRECT_URI

logger = logging.getLogger(__name__)

BASE_URL = "https://api.prod.whoop.com"
AUTH_URL = f"{BASE_URL}/oauth/oauth2/auth"
TOKEN_URL = f"{BASE_URL}/oauth/oauth2/token"
SCOPES = "read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement offline"


class WhoopClient:
    """Client for the Whoop developer API with automatic token refresh."""

    def __init__(self):
        self.client_id = WHOOP_CLIENT_ID
        self.client_secret = WHOOP_CLIENT_SECRET
        self.redirect_uri = WHOOP_REDIRECT_URI
        self.access_token = None
        self.refresh_token_value = None
        self.token_expiry = 0

        # Try loading tokens: DB → env vars → file
        if not self._load_tokens_from_db():
            if not self._load_tokens_from_env():
                if TOKEN_PATH.exists():
                    self._load_tokens_from_file()

    # ── Auth URL ──────────────────────────────────────────────────────

    def generate_auth_url(self) -> tuple[str, str]:
        """Build the OAuth2 authorization URL. Returns (url, state)."""
        self._oauth_state = secrets.token_urlsafe(32)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": self._oauth_state,
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", self._oauth_state

    # ── Token exchange ────────────────────────────────────────────────

    def exchange_code(self, code: str) -> dict:
        """Exchange an authorization code for access + refresh tokens."""
        resp = http_requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._apply_token_data(data)
        self._save_tokens_to_db()
        return data

    def refresh_token(self) -> dict:
        """Use the refresh token to get a new access token."""
        if not self.refresh_token_value:
            raise RuntimeError("No refresh token available. Re-authorize.")

        resp = http_requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token_value,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._apply_token_data(data)
        self._save_tokens_to_db()
        return data

    # ── Token persistence ─────────────────────────────────────────────

    def _apply_token_data(self, data: dict) -> None:
        """Set in-memory token state and persist to file."""
        self.access_token = data["access_token"]
        self.refresh_token_value = data.get("refresh_token", self.refresh_token_value)
        self.token_expiry = time.time() + data.get("expires_in", 3600)
        try:
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_PATH, "w") as f:
                json.dump({
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token_value,
                    "token_expiry": self.token_expiry,
                }, f, indent=2)
        except OSError as e:
            logger.warning("Could not save tokens to file: %s", e)

    def _load_tokens_from_db(self) -> bool:
        """Load the most recent tokens from the database."""
        try:
            from database import SessionLocal, Token
            session = SessionLocal()
            try:
                row = session.query(Token).order_by(Token.id.desc()).first()
                if row:
                    self.access_token = row.access_token
                    self.refresh_token_value = row.refresh_token
                    self.token_expiry = row.expiry
                    return True
            finally:
                session.close()
        except Exception as e:
            logger.debug("Could not load tokens from DB: %s", e)
        return False

    def _load_tokens_from_env(self) -> bool:
        """Load tokens from environment variables."""
        access = os.environ.get("WHOOP_ACCESS_TOKEN")
        refresh = os.environ.get("WHOOP_REFRESH_TOKEN")
        expiry = os.environ.get("WHOOP_TOKEN_EXPIRY")
        if access and refresh:
            self.access_token = access
            self.refresh_token_value = refresh
            self.token_expiry = float(expiry) if expiry else 0
            return True
        return False

    def _load_tokens_from_file(self) -> None:
        """Load tokens from data/tokens.json."""
        with open(TOKEN_PATH) as f:
            data = json.load(f)
        self.access_token = data["access_token"]
        self.refresh_token_value = data.get("refresh_token")
        self.token_expiry = data.get("token_expiry", 0)

    def _save_tokens_to_db(self) -> None:
        """Save current tokens to the database (upsert — single row)."""
        try:
            from database import SessionLocal, Token
            session = SessionLocal()
            try:
                existing = session.query(Token).first()
                if existing:
                    existing.access_token = self.access_token
                    existing.refresh_token = self.refresh_token_value
                    existing.expiry = self.token_expiry
                else:
                    session.add(Token(
                        access_token=self.access_token,
                        refresh_token=self.refresh_token_value,
                        expiry=self.token_expiry,
                    ))
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.warning("Could not save tokens to DB: %s", e)

    # ── Request helpers ───────────────────────────────────────────────

    def _request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request with auto-refresh and retry."""
        if time.time() >= self.token_expiry - 60:
            self.refresh_token()

        url = f"{BASE_URL}{endpoint}"
        max_retries = 3

        for attempt in range(max_retries + 1):
            headers = {"Authorization": f"Bearer {self.access_token}"}
            resp = http_requests.get(url, headers=headers, params=params)

            if resp.status_code == 401 and attempt == 0:
                self.refresh_token()
                continue

            if resp.status_code == 429 and attempt < max_retries:
                wait = int(resp.headers.get("Retry-After", 60))
                logger.info("Rate limited. Waiting %ds (retry %d/%d)...", wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

    def _paginate(self, endpoint: str, start: str | None = None, end: str | None = None) -> list[dict]:
        """Paginate through a collection endpoint, returning all records."""
        all_records = []
        params = {"limit": 25}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        first_page = True
        while True:
            if not first_page:
                time.sleep(0.5)
            first_page = False

            data = self._request(endpoint, params)
            records = data.get("records", [])
            all_records.extend(records)

            next_token = data.get("next_token")
            if not next_token:
                break
            params["nextToken"] = next_token

        return all_records

    # ── Public API methods ────────────────────────────────────────────

    def get_workouts(self, start: str | None = None, end: str | None = None) -> list[dict]:
        """Fetch all workouts, optionally filtered by ISO date range."""
        return self._paginate("/developer/v2/activity/workout", start, end)

    def get_recovery(self, start: str | None = None, end: str | None = None) -> list[dict]:
        """Fetch all recovery records, optionally filtered by ISO date range."""
        return self._paginate("/developer/v2/recovery", start, end)

    def get_profile(self) -> dict:
        """Get the authenticated user's basic profile."""
        return self._request("/developer/v2/user/profile/basic")
