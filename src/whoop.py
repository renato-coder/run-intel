"""
Whoop API client for Run Intel.

Handles OAuth2 authorization, token management, and all API calls
to the Whoop developer API (v2).

Token resolution order:
  1. Database (tokens table)
  2. Environment variables (WHOOP_ACCESS_TOKEN, WHOOP_REFRESH_TOKEN, WHOOP_TOKEN_EXPIRY)
  3. Local file (data/tokens.json)

On refresh, new tokens are saved to the database.
"""

import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_URL = "https://api.prod.whoop.com"
AUTH_URL = f"{BASE_URL}/oauth/oauth2/auth"
TOKEN_URL = f"{BASE_URL}/oauth/oauth2/token"
SCOPES = "read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement offline"

TOKEN_PATH = Path(__file__).resolve().parent.parent / "data" / "tokens.json"


class WhoopClient:
    """Client for the Whoop developer API with automatic token refresh."""

    def __init__(self):
        self.client_id = os.environ["WHOOP_CLIENT_ID"]
        self.client_secret = os.environ["WHOOP_CLIENT_SECRET"]
        self.redirect_uri = os.environ["WHOOP_REDIRECT_URI"]
        self.access_token = None
        self.refresh_token_value = None
        self.token_expiry = 0

        # Try loading tokens: DB → env vars → file
        if not self._load_tokens_from_db():
            if not self._load_tokens_from_env():
                if TOKEN_PATH.exists():
                    self._load_tokens_from_file()

    # ── Auth URL ──────────────────────────────────────────────────────

    def generate_auth_url(self):
        """Build the OAuth2 authorization URL with all required scopes.
        Returns (url, state) so the caller can validate state on redirect."""
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

    def exchange_code(self, code):
        """Exchange an authorization code for access + refresh tokens."""
        resp = requests.post(
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

    def refresh_token(self):
        """Use the refresh token to get a new access token."""
        if not self.refresh_token_value:
            raise RuntimeError("No refresh token available. Re-authorize.")

        resp = requests.post(
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

    def _apply_token_data(self, data):
        """Set in-memory token state from an OAuth response."""
        self.access_token = data["access_token"]
        self.refresh_token_value = data.get("refresh_token", self.refresh_token_value)
        self.token_expiry = time.time() + data.get("expires_in", 3600)

    def _load_tokens_from_db(self):
        """Load the most recent tokens from the database. Returns True on success."""
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
        except Exception:
            pass
        return False

    def _load_tokens_from_env(self):
        """Load tokens from environment variables. Returns True on success."""
        access = os.environ.get("WHOOP_ACCESS_TOKEN")
        refresh = os.environ.get("WHOOP_REFRESH_TOKEN")
        expiry = os.environ.get("WHOOP_TOKEN_EXPIRY")
        if access and refresh:
            self.access_token = access
            self.refresh_token_value = refresh
            self.token_expiry = float(expiry) if expiry else 0
            return True
        return False

    def _load_tokens_from_file(self):
        """Load tokens from data/tokens.json."""
        with open(TOKEN_PATH) as f:
            data = json.load(f)
        self.access_token = data["access_token"]
        self.refresh_token_value = data.get("refresh_token")
        self.token_expiry = data.get("token_expiry", 0)

    def _save_tokens_to_db(self):
        """Save current tokens to the database."""
        try:
            from database import SessionLocal, Token
            session = SessionLocal()
            try:
                token = Token(
                    access_token=self.access_token,
                    refresh_token=self.refresh_token_value,
                    expiry=self.token_expiry,
                )
                session.add(token)
                session.commit()
            finally:
                session.close()
        except Exception as e:
            print(f"Warning: could not save tokens to DB: {e}")

    # ── Request helpers ───────────────────────────────────────────────

    def _request(self, endpoint, params=None):
        """
        Make an authenticated GET request.
        Automatically refreshes the access token on 401.
        Retries up to 3 times on 429 rate limit responses.
        """
        # Proactively refresh if token is expired or about to expire
        if time.time() >= self.token_expiry - 60:
            self.refresh_token()

        url = f"{BASE_URL}{endpoint}"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        for attempt in range(4):  # initial + 3 retries
            resp = requests.get(url, headers=headers, params=params)

            # Retry once on 401 after refreshing
            if resp.status_code == 401:
                self.refresh_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                resp = requests.get(url, headers=headers, params=params)

            # Handle 429 rate limit with retry
            if resp.status_code == 429 and attempt < 3:
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"  Rate limited. Waiting {wait}s (retry {attempt + 1}/3)...")
                time.sleep(wait)
                continue

            break

        resp.raise_for_status()
        return resp.json()

    def _paginate(self, endpoint, start=None, end=None):
        """
        Paginate through a collection endpoint, returning all records.
        Handles the nextToken pagination pattern (limit max 25 per page).
        """
        all_records = []
        params = {"limit": 25}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        first_page = True
        while True:
            # Small delay between pages to avoid hitting rate limits
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

    def get_workouts(self, start=None, end=None):
        """Fetch all workouts, optionally filtered by ISO date range."""
        return self._paginate("/developer/v2/activity/workout", start, end)

    def get_recovery(self, start=None, end=None):
        """Fetch all recovery records, optionally filtered by ISO date range."""
        return self._paginate("/developer/v2/recovery", start, end)

    def get_sleep(self, start=None, end=None):
        """Fetch all sleep records, optionally filtered by ISO date range."""
        return self._paginate("/developer/v2/activity/sleep", start, end)

    def get_cycles(self, start=None, end=None):
        """Fetch all physiological cycles."""
        return self._paginate("/developer/v2/cycle", start, end)

    def get_profile(self):
        """Get the authenticated user's basic profile."""
        return self._request("/developer/v2/user/profile/basic")

    def get_body(self):
        """Get the authenticated user's body measurements."""
        return self._request("/developer/v2/user/measurement/body")
