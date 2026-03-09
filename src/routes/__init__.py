"""Route blueprints for Run Intel."""

from routes.briefing import bp as briefing_bp
from routes.runs import bp as runs_bp


def register_blueprints(app):
    """Register all route blueprints with the Flask app."""
    app.register_blueprint(briefing_bp)
    app.register_blueprint(runs_bp)
