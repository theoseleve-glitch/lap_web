"""Tests for API JSON contract enforcement."""
import pytest

from web.app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_api_404_returns_json(client):
    """GET /api/v1/nonexistent must return JSON, not HTML."""
    resp = client.get("/api/v1/nonexistent")
    assert resp.content_type.startswith("application/json"), \
        f"Expected JSON, got {resp.content_type}"
    body = resp.get_json()
    assert body["ok"] is False
    assert body.get("meta", {}).get("request_id") is not None


def test_api_error_includes_request_id(client):
    """Every API error must include meta.request_id."""
    resp = client.get("/api/v1/nonexistent")
    body = resp.get_json()
    assert body.get("meta", {}).get("request_id") is not None


def test_html_guard_catches_html_on_api_path(app):
    """If a route accidentally returns HTML on /api/*, the guard rewrites it."""
    @app.route("/api/v1/_test_html_leak")
    def _leak_html():
        return "<!DOCTYPE html><html><body>oops</body></html>", 200

    with app.test_client() as c:
        resp = c.get("/api/v1/_test_html_leak")
        assert resp.content_type.startswith("application/json"), \
            f"Guard should rewrite HTML to JSON, got {resp.content_type}"
        body = resp.get_json()
        assert body["ok"] is False
        assert body["error"]["code"] == "API_HTML_RESPONSE"


def test_options_preflight_not_intercepted_by_guard(client):
    """OPTIONS preflight on /api/* must return 200, not 500 from HTML guard."""
    resp = client.options(
        "/api/v1/dashboard/stats",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert resp.status_code == 200, \
        f"OPTIONS preflight should be 200, got {resp.status_code}"


def test_html_guard_allows_attachment_downloads(app):
    """Report download (Content-Disposition: attachment) is exempt from guard."""
    import io

    from flask import send_file

    @app.route("/api/v1/_test_attachment")
    def _attachment():
        buf = io.BytesIO(b"<html>report</html>")
        return send_file(buf, mimetype="text/html", as_attachment=True,
                         download_name="report.html")

    with app.test_client() as c:
        resp = c.get("/api/v1/_test_attachment")
        assert resp.content_type.startswith("text/html"), \
            "Attachment should NOT be rewritten"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
