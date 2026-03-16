"""
Flask application factory for the telemetry dashboard.

Usage::

    from web.app import create_app
    app = create_app()
    app.run(host="127.0.0.1", port=5000)
"""

from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Iterable

from flask import Flask, Response, g, jsonify, render_template, request
from flask.json.provider import DefaultJSONProvider

from .config import Config


class _NaNSafeJSONProvider(DefaultJSONProvider):
    """JSON provider that replaces NaN/Infinity with null.

    Python's json.dumps allows NaN by default, but NaN is not valid JSON
    per RFC 8259 and causes SyntaxError in browser JSON.parse().
    """

    def dumps(self, obj: Any, **kwargs: Any) -> str:
        kwargs.setdefault("default", self.default)
        # Use allow_nan=False so json.dumps raises on NaN, then handle it
        # via a custom default. But simpler: sanitize before encoding.
        return super().dumps(_sanitize_nan(obj), **kwargs)


def _sanitize_nan(obj: Any) -> Any:
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

    # Trust X-Forwarded-For from reverse proxy (Caddy) so request.remote_addr
    # returns the real client IP. Only applied in production (USE_PG=1).
    # x_for=1 means trust one proxy hop (Caddy).
    if cfg.USE_PG:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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

    try:
        from .openapi import register_openapi
        register_openapi(app)
        logger.debug("Registered OpenAPI spec at /api/v1/openapi.json and Swagger UI at /api/v1/docs")
    except ImportError:
        logger.debug("OpenAPI module not available — skipping")

    # Access logging middleware (method/path/status/latency with redaction)
    try:
        from .middleware.access_log import init_access_log
        init_access_log(app)
        logger.debug("Initialized access log middleware")
    except ImportError:
        logger.debug("Access log middleware not available — skipping")

    # CORS — custom middleware (replaced flask_cors for full control).
    app.config["CORS_ALLOWED_ORIGINS"] = cfg.CORS_ALLOWED_ORIGINS
    from .middleware.cors import init_cors
    init_cors(app)

    # Ensure OPTIONS preflight returns 200 even for non-existent routes.
    # Browsers require 2xx on preflight; the CORS after_request hook adds
    # headers to whatever response is returned here.
    @app.before_request
    def _handle_preflight() -> Response | None:
        from flask import make_response
        from flask import request as req
        if req.method == "OPTIONS":
            resp = make_response("", 200)
            resp.content_type = "application/json"
            return resp
        return None

    # Guard: reject oversized JSON bodies on non-upload API endpoints.
    # The global MAX_CONTENT_LENGTH is 12 GB for file uploads, but JSON
    # API bodies (PATCH, POST with application/json) should never exceed 1 MB.
    _MAX_JSON_BODY = 1 * 1024 * 1024  # 1 MB

    @app.before_request
    def _json_body_size_guard() -> Response | tuple[Response, int] | None:
        if request.method in ("POST", "PUT", "PATCH") and request.path.startswith("/api/v1/"):
            ct = request.content_type or ""
            # Skip file uploads (multipart form data)
            if "multipart/form-data" in ct:
                return
            content_length = request.content_length
            if content_length and content_length > _MAX_JSON_BODY:
                from .api_utils import ErrorCode as _EC
                from .api_utils import api_error as _ae
                return _ae(_EC.VALIDATION_ERROR,
                           "Request body too large (max 1 MB for JSON endpoints)",
                           status=413)

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
        from .db_pg import _get_pg_url, close_pg, init_pg
        app.teardown_appcontext(close_pg)

        with app.app_context():
            init_pg()
            # NOTE: track sync from tracks.json removed. Tracks are created
            # by the pipeline on upload (track_detection → upsert_track).
            # The old sync_tracks_from_json() ran on every worker boot and
            # re-inserted deleted tracks, causing a "zombie tracks" bug.
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
        # Legacy tracks routes removed — replaced by api_v1_entities tracks endpoints
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
        ('.routes.data_v2_channels',   'bp', 'data_v2_channels_bp'), # Rich telemetry channel endpoints
        ('.routes.api_v1_entities',    'bp', 'api_v1_entities_bp'), # Entity CRUD (drivers, tracks)
        ('.routes.api_changelog',      'bp', 'api_changelog_bp'),  # API changelog endpoint
        ('.routes.api_rss',            'bp', 'api_rss_bp'),        # RSS feed endpoint
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
            from .middleware.auth import auth_middleware
            from .routes.auth import api_v1_bp
            from .routes.auth import bp as auth_bp
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
                entitlement_middleware,
                record_successful_usage,
            )
            app.before_request(entitlement_middleware)
            app.after_request(record_successful_usage)
            logger.debug("Registered entitlement middleware")
            from .routes.teams import bp as teams_bp
            from .routes.teams import invitations_bp
            from .routes.workspaces import bp as workspaces_bp
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

            # Endurance upload flow (detect + process endpoints)
            from .routes.endurance_upload import bp as endurance_upload_bp
            app.register_blueprint(endurance_upload_bp)
            logger.debug("Registered endurance_upload blueprint")
        except Exception as exc:
            logger.error("Failed to register auth blueprints: %s", exc)

    # ── i18n: load translations on each request ──
    @app.before_request
    def _load_i18n() -> None:
        from .i18n import SUPPORTED_LANGUAGES, load_translations
        lang = request.cookies.get("lang") or request.args.get("lang", "en")
        if lang not in SUPPORTED_LANGUAGES:
            lang = "en"
        g.t = load_translations(lang)
        g.lang = lang
        g.supported_languages = SUPPORTED_LANGUAGES

    @app.context_processor
    def _inject_i18n() -> dict[str, Any]:
        return {
            "t": getattr(g, "t", {}),
            "lang": getattr(g, "lang", "en"),
            "supported_languages": getattr(g, "supported_languages", ["en"]),
        }

    # ── Legacy /api/session/ path rewriting ────────────────────────
    # The desktop tool's vanilla JS modules call /api/session/<id>/<endpoint>
    # but the re-port moved all data endpoints to /api/v1/sessions/<id>/<endpoint>.
    # This WSGI middleware transparently rewrites legacy paths so both the
    # desktop tool and SaaS vanilla chart modules work.
    import re as _re

    _GPS_LAP_RE = _re.compile(r'/api/session/([^/]+)/gps/(\d+)$')
    _GG_LAP_RE = _re.compile(r'/api/session/([^/]+)/gg/(\d+)$')

    class _LegacyApiRewriteMiddleware:
        """Rewrite /api/session/ paths to /api/v1/sessions/ equivalents."""

        _SUB_PATH_MAP = [
            ('gg_data',          'gg-data'),
            ('lap_times',        'laps'),
            ('sector-analysis',  'sector_times'),
            ('corner-coaching',  'corners'),
        ]

        def __init__(self, wsgi_app: Any, gps_re: _re.Pattern[str], gg_re: _re.Pattern[str]) -> None:
            self.wsgi_app = wsgi_app
            self._gps_re = gps_re
            self._gg_re = gg_re

        def __call__(self, environ: dict[str, Any], start_response: Any) -> Iterable[bytes]:
            path = environ.get('PATH_INFO', '')
            if '/api/session/' not in path:
                return self.wsgi_app(environ, start_response)

            qs = environ.get('QUERY_STRING', '')

            # /api/session/{id}/gps/{lap} → /api/v1/sessions/{id}/gps-trace?lap={lap}
            m = self._gps_re.search(path)
            if m:
                sid, lap = m.group(1), m.group(2)
                environ['PATH_INFO'] = path[:m.start()] + '/api/v1/sessions/' + sid + '/gps-trace'
                parts = [qs] if qs else []
                parts.append('lap=' + lap)
                environ['QUERY_STRING'] = '&'.join(parts)
                return self.wsgi_app(environ, start_response)

            # /api/session/{id}/gg/{lap} → /api/v1/sessions/{id}/gg-data?lap={lap}
            m = self._gg_re.search(path)
            if m:
                sid, lap = m.group(1), m.group(2)
                environ['PATH_INFO'] = path[:m.start()] + '/api/v1/sessions/' + sid + '/gg-data'
                parts = [qs] if qs else []
                parts.append('lap=' + lap)
                environ['QUERY_STRING'] = '&'.join(parts)
                return self.wsgi_app(environ, start_response)

            # Prefix rewrite: /api/session/ → /api/v1/sessions/
            new_path = path.replace('/api/session/', '/api/v1/sessions/')

            # Sub-path name mapping (order matters: longer names first)
            for old_name, new_name in self._SUB_PATH_MAP:
                suffix = '/' + old_name
                if new_path.endswith(suffix):
                    new_path = new_path[:-len(old_name)] + new_name
                    break

            environ['PATH_INFO'] = new_path
            return self.wsgi_app(environ, start_response)

    app.wsgi_app = _LegacyApiRewriteMiddleware(app.wsgi_app, _GPS_LAP_RE, _GG_LAP_RE)

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
        def __init__(self, wsgi_app: Any) -> None:
            self.wsgi_app = wsgi_app
        def __call__(self, environ: dict[str, Any], start_response: Any) -> Iterable[bytes]:
            path = environ.get("PATH_INFO", "")
            decoded = path.replace("%2B", "+").replace("%2b", "+")
            if decoded != path:
                environ["PATH_INFO"] = decoded
            return self.wsgi_app(environ, start_response)

    app.wsgi_app = _DecodePathMiddleware(app.wsgi_app)

    # Error handlers — return JSON for API routes, HTML for browser pages.
    # All API paths use api_error() so responses include meta.request_id.
    from .api_utils import ErrorCode as _EC
    from .api_utils import api_error as _api_error

    def _wants_html() -> bool:
        """True only for desktop/browser requests that explicitly want HTML."""
        if app.config.get("AUTH_REQUIRED"):
            # Production API server — always return JSON
            return False
        accept = request.headers.get("Accept", "")
        return "text/html" in accept and "application/json" not in accept

    # Catch-all: API root returns JSON
    @app.route("/", defaults={"path": ""})
    def _catch_root(path: str) -> Response | tuple[str, int]:
        if _wants_html():
            return render_template("dashboard.html"), 200
        return _api_error(_EC.NOT_FOUND, "Not found. API endpoints are under /api/v1/", status=404)

    @app.errorhandler(404)
    def page_not_found(e: Exception) -> Response | tuple[str, int]:
        if not _wants_html():
            return _api_error(_EC.NOT_FOUND, "Resource not found", status=404)
        return render_template("404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(e: Exception) -> Response | tuple[str, int]:
        if not _wants_html():
            return _api_error(_EC.VALIDATION_ERROR, "Method not allowed", status=405)
        return render_template("404.html"), 405

    @app.errorhandler(413)
    def request_entity_too_large(e: Exception) -> Response | tuple[str, int]:
        if not _wants_html():
            return _api_error(_EC.FILE_TOO_LARGE,
                              "File too large. Maximum upload size is 12 GB.",
                              status=413)
        return render_template("500.html"), 413

    @app.errorhandler(500)
    def internal_error(e: Exception) -> Response | tuple[str, int]:
        logger.exception("Unhandled 500 error on %s %s", request.method, request.path)
        if not _wants_html():
            return _api_error(_EC.INTERNAL_ERROR, "Internal server error", status=500)
        return render_template("500.html"), 500

    @app.errorhandler(Exception)
    def unhandled_exception(e: Exception) -> Response | tuple[str, int]:
        logger.exception("Unhandled exception on %s %s", request.method, request.path)
        if not _wants_html():
            return _api_error(_EC.INTERNAL_ERROR, "Internal server error", status=500)
        return render_template("500.html"), 500

    # Security headers (defense-in-depth, also set by Caddy in prod)
    @app.after_request
    def set_security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-XSS-Protection", "0")  # modern browsers: CSP is preferred
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        return response

    # Cache static assets (CSS, JS, images) for 1 day.
    # Cache read-only API GETs for 60s (private, must-revalidate).
    @app.after_request
    def set_cache_headers(response: Response) -> Response:
        if request.path.startswith("/static/"):
            response.cache_control.max_age = 86400
            response.cache_control.public = True
        elif (
            request.method == "GET"
            and request.path.startswith("/api/")
            and response.status_code == 200
            and "Cache-Control" not in response.headers
        ):
            # Fallback: always revalidate so mutations (delete, update)
            # are reflected immediately.  ETag still saves bandwidth.
            response.cache_control.private = True
            response.cache_control.no_cache = True
        # Add API version header for client diagnostics
        if request.path.startswith("/api/"):
            from pipeline_version import PIPELINE_VERSION
            response.headers["X-API-Version"] = PIPELINE_VERSION
        return response

    # ETag for JSON API responses — enables 304 Not Modified.
    @app.after_request
    def set_etag(response: Response) -> Response:
        if (
            request.method == "GET"
            and request.path.startswith("/api/")
            and response.status_code == 200
            and response.content_type
            and response.content_type.startswith("application/json")
        ):
            response.add_etag()
            # Return 304 if client's If-None-Match matches
            return response.make_conditional(request)
        return response

    # Gzip compression for API JSON responses > 1 KB when client accepts it.
    @app.after_request
    def _gzip_response(response: Response) -> Response:
        if (
            not request.path.startswith("/api/")
            or response.status_code < 200
            or response.status_code >= 300
            or not response.content_type
            or not response.content_type.startswith("application/json")
            or response.content_length is not None and response.content_length < 1024
            or "Content-Encoding" in response.headers
            or "gzip" not in request.headers.get("Accept-Encoding", "")
        ):
            return response
        import gzip as _gzip

        data = response.get_data()
        if len(data) < 1024:
            return response
        compressed = _gzip.compress(data, compresslevel=6)
        response.set_data(compressed)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(compressed))
        # Vary so caches distinguish compressed vs uncompressed
        vary = response.headers.get("Vary", "")
        if "Accept-Encoding" not in vary:
            response.headers["Vary"] = f"{vary}, Accept-Encoding".lstrip(", ")
        return response

    # Guard: ensure /api/* never returns HTML to JSON consumers.
    @app.after_request
    def _json_guard(response: Response) -> Response:
        """Intercept HTML responses on /api/* paths.

        If a route under /api/ accidentally returns text/html (e.g. an old
        template route leaked into the API namespace), replace the response
        with a structured JSON error so the SaaS frontend never sees
        'Unexpected token <'.
        """
        if not request.path.startswith("/api/"):
            return response
        # CORS preflight returns empty body with text/html content-type;
        # don't intercept it — the 200 from _handle_preflight is correct.
        if request.method == "OPTIONS":
            return response
        # Exempt file-download responses (report endpoint).
        if "attachment" in (response.headers.get("Content-Disposition") or ""):
            return response

        ct = response.content_type or ""
        is_html_ct = "text/html" in ct

        def _make_html_error() -> Response:
            from .api_utils import ErrorCode as _EC2
            from .api_utils import api_error as _ae
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
        def _debug_template_info() -> tuple[str, int, dict[str, str]]:
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
