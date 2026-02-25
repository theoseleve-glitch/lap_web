"""
Flask application factory for the telemetry dashboard.

Usage::

    from web.app import create_app
    app = create_app()
    app.run(host="127.0.0.1", port=5000)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from .config import Config

logger = logging.getLogger(__name__)


def _resolve_web_dir() -> Path:
    """Return the web/ directory containing templates/ and static/.

    When running inside a PyInstaller bundle, __file__ may point to the
    PYZ archive rather than the real filesystem.  In that case we use
    sys._MEIPASS (the _internal/ folder) which is where PyInstaller
    actually unpacks the bundled data files.
    """
    # Try the normal __file__ path first
    local = Path(__file__).resolve().parent
    if (local / "templates").is_dir() and (local / "static").is_dir():
        return local

    # Frozen PyInstaller build — look in _MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundle = Path(meipass) / "web"
        if (bundle / "templates").is_dir():
            return bundle

    # Fallback: walk up from __file__ looking for web/templates
    for parent in local.parents:
        candidate = parent / "web"
        if (candidate / "templates").is_dir():
            return candidate

    # Last resort — use __file__ parent as-is
    return local


def create_app(config: Config | None = None) -> Flask:
    """Create and configure the Flask application."""
    cfg = config or Config()

    web_dir = _resolve_web_dir()
    logger.info("Web assets directory: %s", web_dir)

    app = Flask(
        __name__,
        template_folder=str(web_dir / "templates"),
        static_folder=str(web_dir / "static"),
    )

    # Load configuration.
    app.config.from_mapping(
        SECRET_KEY=cfg.SECRET_KEY,
        DB_PATH=str(cfg.DB_PATH),
        DATA_RAW_DIR=str(cfg.DATA_RAW_DIR),
        RESULTS_DIR=str(cfg.RESULTS_DIR),
        UPLOAD_DIR=str(cfg.UPLOAD_DIR),
        MAX_CONTENT_LENGTH=cfg.MAX_CONTENT_LENGTH,
        SESSIONS_PER_PAGE=cfg.SESSIONS_PER_PAGE,
    )

    # Ensure directories exist.
    for d in (cfg.DATA_RAW_DIR, cfg.RESULTS_DIR, cfg.UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # Database setup.
    from .db import close_db, init_db, set_default_db_path
    set_default_db_path(cfg.DB_PATH)
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db(cfg.DB_PATH)
        # Sync tracks from file-based tracks.json into SQLite.
        from .db import get_db_connection
        from .models import sync_tracks_from_json
        conn = get_db_connection()
        sync_tracks_from_json(conn)

    # Register blueprints — import each safely so one failure doesn't
    # prevent the rest from loading.
    _blueprint_imports = [
        ('.routes.dashboard',          'bp', 'dashboard_bp'),
        ('.routes.sessions',           'bp', 'sessions_bp'),
        ('.routes.tracks',             'bp', 'tracks_bp'),
        ('.routes.analysis',           'bp', 'analysis_bp'),
        ('.routes.api_data',           'bp', 'api_bp'),
        ('.routes.weekends',           'bp', 'weekends_bp'),
        ('.routes.drivers',            'bp', 'drivers_bp'),
        ('.routes.comparisons',        'bp', 'comparisons_bp'),
        ('.routes.leaderboard',        'bp', 'leaderboard_bp'),
        ('.routes.visualize',          'bp', 'visualize_bp'),
        # ('.routes.data_health',      'bp', 'data_health_bp'),   # Removed per audit
        ('.routes.analytics',          'bp', 'analytics_bp'),
        ('.routes.predictions',        'bp', 'predictions_bp'),
        ('.routes.annotations_routes', 'bp', 'annotations_bp'),
        # ('.routes.dashboards',       'bp', 'dashboards_bp'),   # Removed per audit
        ('.routes.dev_plans',          'bp', 'dev_plans_bp'),
        # ('.routes.exports',          'bp', 'exports_bp'),      # Removed per audit
        ('.routes.karts',              'bp', 'karts_bp'),
        ('.routes.ingest',             'bp', 'ingest_bp'),        # Streaming ingest SSE (INGEST_V2)
    ]

    import importlib
    for mod_name, attr_name, label in _blueprint_imports:
        try:
            mod = importlib.import_module(mod_name, package=__package__)
            bp_obj = getattr(mod, attr_name)
            app.register_blueprint(bp_obj)
            logger.debug("Registered blueprint: %s", label)
        except Exception as exc:
            logger.error("Failed to register blueprint %s (%s): %s", label, mod_name, exc)

    # URL-decode percent-encoded path segments (e.g. %2B → +).
    # Werkzeug does NOT auto-decode %2B in path segments, so session IDs
    # containing '+' would 404 when JS uses encodeURIComponent().
    # We use a WSGI middleware to decode the PATH_INFO before Flask
    # routing, so routes match naturally with '+' characters.
    class _DecodePathMiddleware:
        """Decode %2B → '+' in PATH_INFO before Flask's URL routing.

        Only decodes %2B specifically (not all percent-encoded chars)
        to avoid altering routing semantics for %2F (/) etc.
        """
        def __init__(self, wsgi_app):
            self.wsgi_app = wsgi_app
        def __call__(self, environ, start_response):
            path = environ.get("PATH_INFO", "")
            decoded = path.replace("%2B", "+").replace("%2b", "+")
            if decoded != path:
                environ["PATH_INFO"] = decoded
            return self.wsgi_app(environ, start_response)

    app.wsgi_app = _DecodePathMiddleware(app.wsgi_app)

    # Error handlers.
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def request_entity_too_large(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "File too large. Maximum upload size is 12 GB."}), 413
        return render_template("500.html"), 413

    @app.errorhandler(500)
    def internal_error(e):
        return render_template("500.html"), 500

    # Cache static assets (CSS, JS, images) for 1 day.
    @app.after_request
    def set_cache_headers(response):
        if request.path.startswith("/static/"):
            response.cache_control.max_age = 86400
            response.cache_control.public = True
        return response

    # Debug endpoint to check template loading (only in debug mode)
    if app.debug:
        @app.route("/_debug/template-info")
        def _debug_template_info():
            import json
            info = {
                "template_folder": app.template_folder,
                "static_folder": app.static_folder,
                "jinja_loader": str(app.jinja_loader),
                "searchpath": list(app.jinja_loader.searchpath) if hasattr(app.jinja_loader, 'searchpath') else "N/A",
                "template_exists": {},
                "base_html_snippet": "",
            }
            for name in ["base.html", "dashboard.html", "data_health.html"]:
                try:
                    src = app.jinja_loader.get_source(app.jinja_env, name)
                    info["template_exists"][name] = len(src[0])
                    if name == "base.html":
                        info["base_html_snippet"] = src[0][:2000]
                except Exception as e:
                    info["template_exists"][name] = str(e)
            info["routes_count"] = len(list(app.url_map.iter_rules()))
            return json.dumps(info, indent=2, default=str), 200, {"Content-Type": "application/json"}

    logger.info(
        "Telemetry dashboard ready (db=%s, %d routes).",
        cfg.DB_PATH, len(list(app.url_map.iter_rules())),
    )

    return app
