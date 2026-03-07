# Run Intel

Running performance tracker powered by Whoop biometric data. Web dashboard with coaching insights, trend analysis, and morning briefings.

## Features

- **Morning Briefing** — daily status with recovery-based training recommendations
- **Coaching Insights** — AI-powered pace recommendations based on HR trends
- **OAuth2 Whoop integration** — auto-pulls HR, strain, recovery, and zone data
- **Trend Analysis** — pace vs HR chart, 7d vs 30d snapshot, cardiac drift detection
- **Shoe Tracker** — mileage tracking with replacement alerts
- **Run Logging** — log distance, time, and shoe with auto-matched Whoop workout

## Setup

```bash
# 1. Clone and install dependencies
git clone <repo-url> && cd run-intel
pip install -r requirements.txt

# 2. Create .env with required configuration
cat > .env <<EOF
DATABASE_URL=postgresql://user:pass@host:5432/runintel
WHOOP_CLIENT_ID=your_client_id
WHOOP_CLIENT_SECRET=your_client_secret
WHOOP_REDIRECT_URI=https://whoop.com
APP_PASSWORD=your_secure_password
SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
EOF

# 3. Authorize with Whoop (one-time)
python src/auth.py

# 4. (Optional) Backfill from CSV if you have historical data
python src/upload_history.py
```

## Usage

Start the web dashboard:

```bash
# Development
python src/app.py

# Production (via Procfile)
gunicorn src.app:app --bind 0.0.0.0:$PORT
```

Open the dashboard, log in with your `APP_PASSWORD`, and start logging runs.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `WHOOP_CLIENT_ID` | Yes | Whoop API client ID |
| `WHOOP_CLIENT_SECRET` | Yes | Whoop API client secret |
| `WHOOP_REDIRECT_URI` | Yes | OAuth redirect URI |
| `APP_PASSWORD` | Yes | Dashboard login password |
| `SESSION_SECRET` | Yes | Secret for session token signing |
| `FLASK_DEBUG` | No | Set to `true` for debug mode (default: false) |
| `PORT` | No | Server port (default: 5050) |

## Project Structure

```
src/
  app.py              Flask web app (routes, auth, API endpoints)
  config.py           Centralized configuration with validation
  database.py         SQLAlchemy models and session management
  whoop.py            Whoop API client (OAuth2, token refresh, pagination)
  briefing.py         Morning briefing analysis engine
  utils.py            Shared utility functions
  auth.py             One-time Whoop authorization script
  upload_history.py   CSV-to-database seeder
  static/
    index.html        React SPA frontend
data/
  tokens.json         OAuth tokens (gitignored)
```
