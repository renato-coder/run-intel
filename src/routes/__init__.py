"""Route blueprints for Run Intel."""

from routes.body_comp import bp as body_comp_bp
from routes.briefing import bp as briefing_bp
from routes.metrics import bp as metrics_bp
from routes.nutrition import bp as nutrition_bp
from routes.profile import bp as profile_bp
from routes.runs import bp as runs_bp


def register_blueprints(app):
    """Register all route blueprints with the Flask app."""
    app.register_blueprint(briefing_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(nutrition_bp)
    app.register_blueprint(body_comp_bp)
    app.register_blueprint(metrics_bp)
