"""
Flask application factory for the telemetry dashboard.

Usage::

    from web.app import create_app
    app = create_app()
    app.run(host="127.0.0.1", port=5000)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import math

from flask import Flask, g, jsonify, render_template, request
from flask.json.provider import DefaultJSONProvider

from .config import Config


class _NaNSafeJSONProvider(DefaultJSONProvider):
    """JSON provider that replaces NaN/Infinity with null.

    Python's json.dumps allows NaN by default, but NaN is not valid JSON
    per RFC 8259 and causes SyntaxError in browser JSON.parse().
    """

    def dumps(self, obj, **kwargs):
        kwargs.setdefault("default", self.default)
        # Use allow_nan=False so json.dumps raises on NaN, then handle it
        # via a custom default. But simpler: sanitize before encoding.
        return super().dumps(_sanitize_nan(obj), **kwargs)


def _sanitize_nan(obj):
    """Recursively replace NaN/Infinity with None for JSON safety."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_nan(v) for v in obj]
    return obj

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
    cfg.validate()

    web_dir = _resolve_web_dir()
    logger.info("Web assets directory: %s", web_dir)

    app = Flask(
        __name__,
        template_folder=str(web_dir / "templates"),
        static_folder=str(web_dir / "static"),
    )
    app.json_provider_class = _NaNSafeJSONProvider
    app.json = _NaNSafeJSONProvider(app)

    # Load configuration.
    app.config.from_mapping(
        SECRET_KEY=cfg.SECRET_KEY,
        DB_PATH=str(cfg.DB_PATH),
        DATA_RAW_DIR=str(cfg.DATA_RAW_DIR),
        RESULTS_DIR=str(cfg.RESULTS_DIR),
        UPLOAD_DIR=str(cfg.UPLOAD_DIR),
        MAX_CONTENT_LENGTH=cfg.MAX_CONTENT_LENGTH,
        SESSIONS_PER_PAGE=cfg.SESSIONS_PER_PAGE,
        TEMPLATES_AUTO_RELOAD=True,
        # PostgreSQL / auth settings (used by routes and middleware).
        USE_PG=cfg.USE_PG,
        # Note: PG_URL deliberately NOT in app.config (credential exposure).
        # db_pg.py reads it directly from the TELEMETRY_PG_URL env var.
        AUTH_REQUIRED=cfg.AUTH_REQUIRED,
        JWT_SECRET=cfg.JWT_SECRET,
        JWT_ALGORITHM=cfg.JWT_ALGORITHM,
        JWT_ACCESS_EXPIRY_MINUTES=cfg.JWT_ACCESS_EXPIRY_MINUTES,
        JWT_REFRESH_EXPIRY_DAYS=cfg.JWT_REFRESH_EXPIRY_DAYS,
        # OAuth provider credentials
        GOOGLE_CLIENT_ID=cfg.GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET=cfg.GOOGLE_CLIENT_SECRET,
        GITHUB_CLIENT_ID=cfg.GITHUB_CLIENT_ID,
        GITHUB_CLIENT_SECRET=cfg.GITHUB_CLIENT_SECRET,
        OAUTH_REDIRECT_BASE=cfg.OAUTH_REDIRECT_BASE,
        FRONTEND_URL=cfg.FRONTEND_URL,
        RATE_LIMIT_ENABLED=cfg.RATE_LIMIT_ENABLED,
        REDIS_URL=cfg.REDIS_URL,
        HARDENING_SUMMARY=cfg.hardening_summary(),
    )

    logger.info("Startup hardening summary: %s", app.config["HARDENING_SUMMARY"])

    # Phase 4 API infrastructure — request ID, structured logging, metrics.
    try:
        from .api_utils import init_request_id
        from .logging_setup import setup_logging

        init_request_id(app)

        # ── Sentry error tracking ──────────────────────────
        _sentry_dsn = os.environ.get("SENTRY_DSN_API")
        if _sentry_dsn:
            try:
                import sentry_sdk
                sentry_sdk.init(
                    dsn=_sentry_dsn,
                    traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
                    environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
                    release=os.environ.get("SENTRY_RELEASE"),
                )
                logger.info("Sentry initialized for Flask API")
            except ImportError:
                logger.warning("sentry-sdk not installed, skipping Sentry init")

        setup_logging(app)
        logger.debug("Initialized Phase 4 API infrastructure (request_id + logging)")
    except ImportError:
        logger.debug("Phase 4 API modules not yet available — skipping init_request_id / setup_logging")

    try:
        from .metrics import init_metrics
        init_metrics(app)
        logger.debug("Initialized metrics collection")
    except ImportError:
        logger.debug("Metrics module not available — skipping")

    # CORS — allow Next.js frontend origin
    from flask_cors import CORS
    origins = [o.strip() for o in cfg.CORS_ALLOWED_ORIGINS.split(",")]
    CORS(app, origins=origins, supports_credentials=True,
         allow_headers=["Authorization", "Content-Type", "X-Workspace-Id",
                        "Idempotency-Key", "X-CSRF-Token", "X-Request-Id"],
         expose_headers=["X-Request-Id", "Retry-After"],
         always_send=True)

    # Ensure OPTIONS preflight returns 200 even for non-existent routes.
    # Browsers require 2xx on preflight; flask_cors adds CORS headers
    # via after_request but Flask returns 404 for unknown routes.
    @app.before_request
    def _handle_preflight():
        from flask import request as req
        if req.method == "OPTIONS":
            return "", 200

    # Redis client for rate limiting + caching.
    # The rate_limit module's get_redis() reads from app.extensions["redis"].
    redis_url = cfg.REDIS_URL
    if redis_url:
        import redis as redis_lib
        try:
            r = redis_lib.from_url(redis_url, socket_timeout=2, decode_responses=True)
            r.ping()
            app.extensions["redis"] = r
            app.config["REDIS_URL"] = redis_url
            logger.info("Redis connected: %s", redis_url.split("@")[-1] if "@" in redis_url else redis_url)
        except Exception as exc:
            logger.warning("Redis connection failed — rate limiting disabled: %s", exc)

    # Ensure directories exist.
    for d in (cfg.DATA_RAW_DIR, cfg.RESULTS_DIR, cfg.UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # Database setup — route to PostgreSQL or SQLite based on config.
    if cfg.USE_PG:
        from .db_pg import close_pg, init_pg, _get_pg_url
        app.teardown_appcontext(close_pg)

        with app.app_context():
            init_pg()
            # Sync tracks using a standalone connection (not the pool) to avoid
            # Gunicorn pre-fork pool corruption — workers inherit master's pool
            # with stale thread IDs, causing "unkeyed connection" errors.
            import psycopg2, psycopg2.extras
            try:
                raw = psycopg2.connect(_get_pg_url())
                raw.cursor_factory = psycopg2.extras.RealDictCursor
                from .db_pg import PgConnectionWrapper
                from .models import merge_duplicate_tracks, sync_tracks_from_json
                conn = PgConnectionWrapper(raw)
                try:
                    conn.execute("SET app.current_workspace_id = '1'")
                except Exception:
                    pass
                sync_tracks_from_json(conn)
                merged = merge_duplicate_tracks(conn)
                if merged > 0:
                    raw.commit()
                    logger.info("Merged %d duplicate Unknown Track entries.", merged)
                raw.close()
            except Exception as exc:
                logger.warning("Track sync skipped on startup: %s", exc)
    else:
        from .db import close_db, init_db, set_default_db_path
        set_default_db_path(cfg.DB_PATH)
        app.teardown_appcontext(close_db)

        with app.app_context():
            init_db(cfg.DB_PATH)
            from .db import get_db_connection
            from .models import merge_duplicate_tracks, sync_tracks_from_json
            conn = get_db_connection()
            sync_tracks_from_json(conn)
            merged = merge_duplicate_tracks(conn)
            if merged > 0:
                conn.commit()
                logger.info("Merged %d duplicate Unknown Track entries.", merged)

    # Register blueprints — import each safely so one failure doesn't
    # prevent the rest from loading.
    _blueprint_imports = [
        ('.routes.health',             'bp', 'health_bp'),
        ('.routes.dashboard',          'bp', 'dashboard_bp'),
        ('.routes.tracks',             'bp', 'tracks_bp'),
        ('.routes.weekends',           'bp', 'weekends_bp'),
        ('.routes.drivers',            'bp', 'drivers_bp'),
        ('.routes.leaderboard',        'bp', 'leaderboard_bp'),
        ('.routes.analytics',          'bp', 'analytics_bp'),
        ('.routes.predictions',        'bp', 'predictions_bp'),
        ('.routes.annotations_routes', 'bp', 'annotations_bp'),
        ('.routes.dev_plans',          'bp', 'dev_plans_bp'),
        ('.routes.karts',              'bp', 'karts_bp'),
        ('.routes.ingest',             'bp', 'ingest_bp'),        # Streaming ingest SSE (INGEST_V2)
        ('.routes.race_strategy_v2',   'bp', 'race_strategy_v2_bp'),
        ('.routes.sessions_v2',        'bp', 'sessions_v2_bp'),    # Sync upload endpoint
        ('.routes.data_v2',            'bp', 'data_v2_bp'),        # Data-serving API endpoints
        ('.routes.api_v1_entities',    'bp', 'api_v1_entities_bp'), # Entity CRUD (drivers, tracks)
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

    # Auth blueprints (only when PostgreSQL is enabled)
    if cfg.USE_PG:
        try:
            from .routes.auth import bp as auth_bp, api_v1_bp
            from .middleware.auth import auth_middleware
            app.register_blueprint(auth_bp)
            app.register_blueprint(api_v1_bp)
            app.before_request(auth_middleware)
            logger.debug("Registered auth blueprints and middleware")
            # CSRF double-submit cookie validation (after auth, before tenant)
            from .middleware.csrf import csrf_middleware
            app.before_request(csrf_middleware)
            logger.debug("Registered CSRF middleware")
            # Always initialize OAuth (binds to app); providers registered conditionally
            from auth.oauth import init_oauth
            init_oauth(app)
            logger.debug("Initialized OAuth (providers: google=%s, github=%s)",
                         bool(cfg.GOOGLE_CLIENT_ID), bool(cfg.GITHUB_CLIENT_ID))
            from .middleware.tenant import tenant_middleware
            app.before_request(tenant_middleware)
            logger.debug("Registered tenant middleware")
            from .middleware.legacy_guard import init_legacy_guard
            init_legacy_guard(app)
            logger.debug("Registered legacy route guard")
            from .middleware.entitlements import (
                entitlement_middleware, record_successful_usage,
            )
            app.before_request(entitlement_middleware)
            app.after_request(record_successful_usage)
            logger.debug("Registered entitlement middleware")
            from .routes.workspaces import bp as workspaces_bp
            from .routes.teams import bp as teams_bp, invitations_bp
            app.register_blueprint(workspaces_bp)
            app.register_blueprint(teams_bp)
            app.register_blueprint(invitations_bp)
            from .routes.admin import bp as admin_bp
            app.register_blueprint(admin_bp)
            logger.debug("Registered workspace, team, and admin blueprints")
            # Initialize Celery with Flask app context
            from celery_app import make_celery
            celery_inst = make_celery(app)
            app.extensions["celery"] = celery_inst
            logger.debug("Initialized Celery with Flask app context")
            # Register Celery pipeline blueprints
            from .routes.jobs import bp as jobs_bp
            from .routes.versioning import bp as versioning_bp
            app.register_blueprint(jobs_bp)
            app.register_blueprint(versioning_bp)
            logger.debug("Registered Celery pipeline blueprints (jobs, versioning)")

            # Phase 4 v1 endpoint blueprints
            from .routes.api_v1_account import bp as api_v1_account_bp
            app.register_blueprint(api_v1_account_bp)
            logger.debug("Registered Phase 4 v1 blueprints (api_v1_account)")

            # Race strategy v1 API
            from .routes.api_v1_race_strategy import bp as api_v1_race_strategy_bp
            app.register_blueprint(api_v1_race_strategy_bp)
            logger.debug("Registered api_v1_race_strategy blueprint")

            # Stripe billing webhook (no auth required — uses Stripe signature)
            from .routes.billing import bp as billing_bp
            app.register_blueprint(billing_bp)
            logger.debug("Registered billing webhook blueprint")

            # Billing API (authenticated — subscription info, invoices, usage)
            from .routes.api_v1_billing import bp as api_v1_billing_bp
            app.register_blueprint(api_v1_billing_bp)
            logger.debug("Registered api_v1_billing blueprint")

            # Support API (authenticated — ticket creation/listing)
            from .routes.api_v1_support import bp as api_v1_support_bp
            app.register_blueprint(api_v1_support_bp)
            logger.debug("Registered api_v1_support blueprint")

            # Export API (authenticated — generate, list, download exports)
            from .routes.exports import bp as exports_bp
            app.register_blueprint(exports_bp)
            logger.debug("Registered exports blueprint")
        except Exception as exc:
            logger.error("Failed to register auth blueprints: %s", exc)

    # ── i18n: load translations on each request ──
    @app.before_request
    def _load_i18n():
        from .i18n import load_translations, SUPPORTED_LANGUAGES
        lang = request.cookies.get("lang") or request.args.get("lang", "en")
        if lang not in SUPPORTED_LANGUAGES:
            lang = "en"
        g.t = load_translations(lang)
        g.lang = lang
        g.supported_languages = SUPPORTED_LANGUAGES

    @app.context_processor
    def _inject_i18n():
        return {
            "t": getattr(g, "t", {}),
            "lang": getattr(g, "lang", "en"),
            "supported_languages": getattr(g, "supported_languages", ["en"]),
        }

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

    # Error handlers — return JSON for API routes, HTML for browser pages.
    # All API paths use api_error() so responses include meta.request_id.
    from .api_utils import api_error as _api_error, ErrorCode as _EC

    @app.errorhandler(404)
    def page_not_found(e):
        if request.path.startswith("/api/"):
            return _api_error(_EC.NOT_FOUND, "Resource not found", status=404)
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        if request.path.startswith("/api/"):
            return _api_error(_EC.VALIDATION_ERROR, "Method not allowed", status=405)
        return render_template("404.html"), 405

    @app.errorhandler(413)
    def request_entity_too_large(e):
        if request.path.startswith("/api/"):
            return _api_error(_EC.FILE_TOO_LARGE,
                              "File too large. Maximum upload size is 12 GB.",
                              status=413)
        return render_template("500.html"), 413

    @app.errorhandler(500)
    def internal_error(e):
        logger.exception("Unhandled 500 error on %s %s", request.method, request.path)
        if request.path.startswith("/api/"):
            return _api_error(_EC.INTERNAL_ERROR, "Internal server error", status=500)
        return render_template("500.html"), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        logger.exception("Unhandled exception on %s %s", request.method, request.path)
        if request.path.startswith("/api/"):
            return _api_error(_EC.INTERNAL_ERROR, "Internal server error", status=500)
        return render_template("500.html"), 500

    # Cache static assets (CSS, JS, images) for 1 day.
    @app.after_request
    def set_cache_headers(response):
        if request.path.startswith("/static/"):
            response.cache_control.max_age = 86400
            response.cache_control.public = True
        return response

    # Guard: ensure /api/* never returns HTML to JSON consumers.
    @app.after_request
    def _json_guard(response):
        """Intercept HTML responses on /api/* paths.

        If a route under /api/ accidentally returns text/html (e.g. an old
        template route leaked into the API namespace), replace the response
        with a structured JSON error so the SaaS frontend never sees
        'Unexpected token <'.
        """
        if not request.path.startswith("/api/"):
            return response
        # Exempt file-download responses (report endpoint).
        if "attachment" in (response.headers.get("Content-Disposition") or ""):
            return response

        ct = response.content_type or ""
        is_html_ct = "text/html" in ct

        def _make_html_error():
            from .api_utils import api_error as _ae, ErrorCode as _EC2
            resp, code = _ae(
                _EC2.API_HTML_RESPONSE,
                "Endpoint returned HTML instead of JSON",
                status=500,
            )
            return app.make_response((resp, code))

        # If content-type explicitly says HTML, intercept immediately.
        if is_html_ct:
            return _make_html_error()

        # Also catch responses where body starts with HTML even if
        # content-type is unset or generic.
        if response.content_length and response.content_length < 10_000:
            try:
                body_start = response.get_data(as_text=True)[:100].strip().lower()
            except Exception:
                return response
            if body_start.startswith("<!doctype") or body_start.startswith("<html"):
                return _make_html_error()

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

    # Prometheus metrics (optional — graceful when prometheus_client absent)
    from .middleware.metrics import init_metrics as init_prometheus_metrics
    init_prometheus_metrics(app)
    logger.debug("Initialized Prometheus metrics")

    logger.info(
        "Telemetry dashboard ready (db=%s, %d routes, env=%s, hardened=%s).",
        cfg.DB_PATH,
        len(list(app.url_map.iter_rules())),
        cfg.ENV,
        app.config["HARDENING_SUMMARY"],
    )

    return app
