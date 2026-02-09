# Run Intel

Running performance tracker powered by Whoop biometric data. Logs runs with heart rate, strain, and HR zone data from your Whoop band, then analyzes trends over time.

## Features

- **OAuth2 Whoop integration** — securely connects to your Whoop account
- **Run logging** — log distance, time, and shoe with auto-matched Whoop HR data
- **Historical backfill** — pull your entire Whoop running and recovery history
- **Trend analysis** — pace/HR efficiency, cardiac drift detection, rolling averages, recovery correlation, per-shoe breakdown

## Setup

```bash
# 1. Clone and install dependencies
git clone <repo-url> && cd run-intel
pip install -r requirements.txt

# 2. Create .env with your Whoop API credentials
WHOOP_CLIENT_ID=your_client_id
WHOOP_CLIENT_SECRET=your_client_secret
WHOOP_REDIRECT_URI=https://whoop.com

# 3. Authorize with Whoop (one-time)
python src/auth.py

# 4. Backfill historical data
python src/backfill.py
```

## Usage

### Log a run

```bash
# Basic: distance (miles) and time (minutes)
python src/log_run.py 6.2 48.5

# With shoe tracking
python src/log_run.py 6.2 48.5 alphafly
```

Supported shoes: `alphafly`, `evosl`, `cloudmonster`, `zoomfly`

The logger automatically matches the closest Whoop running workout from today and pulls HR, strain, and zone data.

### Analyze trends

```bash
python src/trends.py
```

Outputs:
- **Efficiency** — pace vs HR ratio over time (lower = fitter)
- **Rolling averages** — 7-day and 30-day for pace, HR, strain
- **Cardiac drift** — is your HR creeping up at the same pace? (fatigue signal)
- **Recovery correlation** — do high Whoop recovery scores predict faster runs?
- **Shoe breakdown** — avg pace and HR by shoe model

## Project Structure

```
src/
  whoop.py      Whoop API client (OAuth2, token refresh, pagination)
  auth.py       One-time authorization script
  log_run.py    Log a run with Whoop data
  backfill.py   Pull all historical data
  trends.py     Analysis engine
data/
  tokens.json   OAuth tokens (gitignored)
  runs.csv      Run log
  recovery.csv  Recovery history
```
