"""
Run Intel web dashboard — Flask backend.

Thin assembly layer: auth, security headers, blueprint registration.
All route logic lives in routes/ modules.
"""

import hmac
import logging
import sys
from pathlib import Path

from flask import Flask, jsonify, make_response, redirect, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash

# Add src/ to path so sibling modules resolve under gunicorn
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import APP_PASSWORD, FLASK_DEBUG, PORT, SESSION_SECRET
from database import init_db
from routes import register_blueprints

logger = logging.getLogger(__name__)

# ── Auth setup ────────────────────────────────────────────────────

_PASSWORD_HASH = generate_password_hash(APP_PASSWORD)
AUTH_TOKEN = hmac.new(SESSION_SECRET.encode(), APP_PASSWORD.encode(), "sha256").hexdigest()

app = Flask(__name__, static_folder="static")
app.secret_key = SESSION_SECRET
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB upload limit

limiter = Limiter(get_remote_address, app=app, storage_uri="memory://")

# Create tables on startup
init_db()

# Register route blueprints
register_blueprints(app)


# ── Security headers ──────────────────────────────────────────────

@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not FLASK_DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ── Auth middleware for blueprints ────────────────────────────────

@app.before_request
def check_auth():
    """Enforce auth on all routes except login/logout and static assets."""
    # Skip auth for login/logout
    if request.path in ("/login", "/logout"):
        return None
    # Skip auth for static assets served directly
    if request.path.startswith("/static/"):
        return None
    # Check auth token
    token = request.cookies.get("auth_token", "")
    if not hmac.compare_digest(token, AUTH_TOKEN):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Unauthorized"}), 401
        return redirect("/login")
    return None


# ── Login page ────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Run Intel — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0A0A0A;color:#E0E0E0;font-family:'Outfit',sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh}
.login-card{background:#141414;border:1px solid #1E1E1E;border-radius:12px;
  padding:40px;width:100%;max-width:380px;text-align:center}
.bolt{font-size:32px;color:#00F19F}
h1{font-size:24px;font-weight:700;margin:12px 0 4px}
.subtitle{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#666;margin-bottom:28px}
input[type=password]{width:100%;background:#0A0A0A;border:1px solid #2A2A2A;border-radius:8px;
  padding:12px 14px;color:#E0E0E0;font-family:'JetBrains Mono',monospace;font-size:14px;
  outline:none;margin-bottom:16px;text-align:center;letter-spacing:2px}
input:focus{border-color:#00F19F}
button{width:100%;background:#00F19F;color:#0A0A0A;border:none;border-radius:8px;
  padding:12px;font-family:'Outfit',sans-serif;font-weight:600;font-size:14px;cursor:pointer}
button:hover{opacity:0.85}
.error{color:#FF4D4D;font-size:13px;margin-bottom:12px}
</style>
</head>
<body>
<div class="login-card">
  <div class="bolt">&#9889;</div>
  <h1>Run Intel</h1>
  <div class="subtitle">Powered by Whoop</div>
  {error}
  <form method="POST" action="/login">
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Enter</button>
  </form>
</div>
</body></html>"""


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == "GET":
        token = request.cookies.get("auth_token", "")
        if hmac.compare_digest(token, AUTH_TOKEN):
            return redirect("/")
        return LOGIN_HTML.replace("{error}", "")
    password = request.form.get("password", "")
    if check_password_hash(_PASSWORD_HASH, password):
        resp = make_response(redirect("/"))
        resp.set_cookie(
            "auth_token", AUTH_TOKEN, max_age=60 * 60 * 24 * 30,
            httponly=True, samesite="Lax", secure=not FLASK_DEBUG,
        )
        return resp
    return LOGIN_HTML.replace("{error}", '<div class="error">Wrong password.</div>')


@app.route("/logout")
def logout():
    resp = make_response(redirect("/login"))
    resp.delete_cookie("auth_token")
    return resp


# ── Static serving ────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Error handler ─────────────────────────────────────────────────

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "Upload exceeds 10MB limit"}), 413


@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled exception")
    return jsonify({"error": "Internal server error"}), 500


# ── Startup ───────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Run Intel Dashboard: http://localhost:%d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=FLASK_DEBUG)
