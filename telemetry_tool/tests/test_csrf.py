"""Tests for CSRF double-submit cookie middleware."""
import unittest

from flask import Flask, jsonify


def _make_app(auth_required=True):
    """Create a minimal Flask app with CSRF middleware."""
    app = Flask(__name__)
    app.config["AUTH_REQUIRED"] = auth_required
    app.config["TESTING"] = True

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from web.middleware.csrf import csrf_middleware
    app.before_request(csrf_middleware)

    @app.route("/api/v1/sessions/", methods=["POST"])
    def create_session():
        return jsonify({"ok": True})

    @app.route("/api/v1/sessions/", methods=["GET"])
    def list_sessions():
        return jsonify({"ok": True})

    @app.route("/api/v1/billing/webhook", methods=["POST"])
    def webhook():
        return jsonify({"ok": True})

    return app


class TestCSRFMiddleware(unittest.TestCase):

    def test_blocks_post_without_token(self):
        app = _make_app(auth_required=True)
        with app.test_client() as c:
            resp = c.post("/api/v1/sessions/")
            self.assertEqual(resp.status_code, 403)
            self.assertIn("CSRF", resp.get_json()["error"]["message"])

    def test_allows_matching_token(self):
        app = _make_app(auth_required=True)
        with app.test_client() as c:
            token = "test-csrf-token-value"
            c.set_cookie("csrf_token", token)
            resp = c.post(
                "/api/v1/sessions/",
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(resp.status_code, 200)

    def test_blocks_mismatched_token(self):
        app = _make_app(auth_required=True)
        with app.test_client() as c:
            c.set_cookie("csrf_token", "cookie-value")
            resp = c.post(
                "/api/v1/sessions/",
                headers={"X-CSRF-Token": "different-value"},
            )
            self.assertEqual(resp.status_code, 403)

    def test_skips_webhook(self):
        app = _make_app(auth_required=True)
        with app.test_client() as c:
            resp = c.post("/api/v1/billing/webhook")
            self.assertEqual(resp.status_code, 200)

    def test_skips_when_auth_not_required(self):
        app = _make_app(auth_required=False)
        with app.test_client() as c:
            resp = c.post("/api/v1/sessions/")
            self.assertEqual(resp.status_code, 200)

    def test_allows_get_without_token(self):
        """GET requests should not require CSRF."""
        app = _make_app(auth_required=True)
        with app.test_client() as c:
            resp = c.get("/api/v1/sessions/")
            self.assertEqual(resp.status_code, 200)

    def test_blocks_put_without_token(self):
        """PUT is a mutating method and should require CSRF."""
        app = _make_app(auth_required=True)

        @app.route("/api/v1/sessions/1", methods=["PUT"])
        def update_session():
            return jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.put("/api/v1/sessions/1")
            self.assertEqual(resp.status_code, 403)

    def test_blocks_delete_without_token(self):
        """DELETE is a mutating method and should require CSRF."""
        app = _make_app(auth_required=True)

        @app.route("/api/v1/sessions/1", methods=["DELETE"])
        def delete_session():
            return jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.delete("/api/v1/sessions/1")
            self.assertEqual(resp.status_code, 403)

    def test_blocks_patch_without_token(self):
        """PATCH is a mutating method and should require CSRF."""
        app = _make_app(auth_required=True)

        @app.route("/api/v1/sessions/1", methods=["PATCH"])
        def patch_session():
            return jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.patch("/api/v1/sessions/1")
            self.assertEqual(resp.status_code, 403)

    def test_skips_non_api_v1_paths(self):
        """Paths outside /api/v1/ should not require CSRF."""
        app = _make_app(auth_required=True)

        @app.route("/auth/login", methods=["POST"])
        def login():
            return jsonify({"ok": True})

        with app.test_client() as c:
            resp = c.post("/auth/login")
            self.assertEqual(resp.status_code, 200)

    def test_blocks_only_header_no_cookie(self):
        """Header present but no cookie should be blocked."""
        app = _make_app(auth_required=True)
        with app.test_client() as c:
            resp = c.post(
                "/api/v1/sessions/",
                headers={"X-CSRF-Token": "some-token"},
            )
            self.assertEqual(resp.status_code, 403)
            self.assertIn("missing", resp.get_json()["error"]["message"])

    def test_blocks_only_cookie_no_header(self):
        """Cookie present but no header should be blocked."""
        app = _make_app(auth_required=True)
        with app.test_client() as c:
            c.set_cookie("csrf_token", "some-token")
            resp = c.post("/api/v1/sessions/")
            self.assertEqual(resp.status_code, 403)
            self.assertIn("missing", resp.get_json()["error"]["message"])


class TestCSRFHelpers(unittest.TestCase):

    def test_generate_csrf_token_length(self):
        """Generated tokens should be non-empty URL-safe strings."""
        from web.middleware.csrf import generate_csrf_token
        token = generate_csrf_token()
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 32)

    def test_generate_csrf_token_uniqueness(self):
        """Each call should produce a unique token."""
        from web.middleware.csrf import generate_csrf_token
        tokens = {generate_csrf_token() for _ in range(100)}
        self.assertEqual(len(tokens), 100)

    def test_set_csrf_cookie(self):
        """set_csrf_cookie should attach a csrf_token cookie to the response."""
        from web.middleware.csrf import set_csrf_cookie
        app = Flask(__name__)
        with app.test_request_context():
            from flask import make_response
            resp = make_response("ok")
            set_csrf_cookie(resp, "test-token-value")
            # Check the Set-Cookie header was added
            cookie_headers = [
                h[1] for h in resp.headers if h[0] == "Set-Cookie"
            ]
            self.assertTrue(any("csrf_token=test-token-value" in c for c in cookie_headers))
            # Should NOT be httpOnly (JS needs to read it)
            csrf_cookie = [c for c in cookie_headers if "csrf_token=" in c][0]
            self.assertNotIn("HttpOnly", csrf_cookie)
