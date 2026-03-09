"""Withings routes — OAuth callback and connection status."""

import logging

from flask import Blueprint, jsonify, request

from config import WITHINGS_CLIENT_ID

bp = Blueprint("withings", __name__)
logger = logging.getLogger(__name__)


@bp.route("/api/withings/callback")
def withings_callback():
    """OAuth callback — exchange authorization code for tokens."""
    code = request.args.get("code")
    if not code:
        # Withings tests the callback URL with a plain GET (no params).
        # Must return 200 for their validation to pass.
        return "OK", 200

    try:
        from withings import WithingsClient
        client = WithingsClient()
        client.exchange_code(code)
        return (
            "<html><body style='background:#0A0A0A;color:#00F19F;font-family:sans-serif;"
            "display:flex;align-items:center;justify-content:center;height:100vh'>"
            "<div style='text-align:center'><h1>Withings Connected!</h1>"
            "<p style='color:#888'>You can close this tab and refresh Run Intel.</p>"
            "</div></body></html>"
        )
    except Exception:
        logger.exception("Withings OAuth callback failed")
        return "Authorization failed. Please try again.", 500


@bp.route("/api/withings/status")
def withings_status():
    """Check if Withings is connected (has valid tokens)."""
    if not WITHINGS_CLIENT_ID:
        return jsonify({"connected": False, "configured": False})

    try:
        from withings import WithingsClient
        client = WithingsClient()
        return jsonify({"connected": client.has_tokens(), "configured": True})
    except Exception:
        return jsonify({"connected": False, "configured": True})


@bp.route("/api/withings/auth")
def withings_auth():
    """Redirect to Withings authorization page."""
    if not WITHINGS_CLIENT_ID:
        return jsonify({"error": "Withings not configured"}), 400

    from withings import WithingsClient
    client = WithingsClient()
    auth_url = client.generate_auth_url()
    from flask import redirect
    return redirect(auth_url)
