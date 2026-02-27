"""Tests for hardened file upload validation."""
import io
import os
import sys
import tempfile
import unittest

from flask import Flask

# Ensure telemetry_tool package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_app(tmp_dir):
    """Create minimal Flask app with the upload route."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["DATA_RAW_DIR"] = tmp_dir
    app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024  # 600 MB

    # Register just the api_data blueprint
    from web.routes.api_data import bp
    app.register_blueprint(bp)
    return app


class TestUploadHardening(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _upload(self, app, filename, content, content_type="text/csv"):
        """Helper to POST a file upload."""
        with app.test_client() as c:
            data = {"file": (io.BytesIO(content), filename)}
            return c.post(
                "/api/files/upload",
                data=data,
                content_type="multipart/form-data",
            )

    def test_rejects_binary_file(self):
        """Binary content (ELF header / null bytes) → 400."""
        app = _make_app(self.tmp_dir)
        # ELF magic bytes
        content = b"\x7fELF\x00\x00\x00some binary data"
        resp = self._upload(app, "malware.csv", content)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("binary", resp.get_json()["error"].lower())

    def test_rejects_double_extension(self):
        """Filename like 'data.csv.exe' → 400."""
        app = _make_app(self.tmp_dir)
        content = b"col1,col2\n1,2\n"
        resp = self._upload(app, "data.csv.exe", content)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(".csv", resp.get_json()["error"])

    def test_rejects_single_column_csv(self):
        """CSV with only 1 column → 400."""
        app = _make_app(self.tmp_dir)
        content = b"only_one_column\nvalue1\nvalue2\n"
        resp = self._upload(app, "single.csv", content)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("2 columns", resp.get_json()["error"])

    def test_accepts_valid_csv(self):
        """Valid 2+ column CSV → 200."""
        app = _make_app(self.tmp_dir)
        content = b"speed,time,lat,lon\n100,1.0,45.0,9.0\n"
        resp = self._upload(app, "session.csv", content)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("name", data)

    def test_accepts_latin1_csv(self):
        """Latin-1 encoded CSV with accented chars → 200."""
        app = _make_app(self.tmp_dir)
        # Latin-1 encoded content with accented characters
        content = "Vitesse,Temps\n100,1.0\nMüller,2.0\n".encode("latin-1")
        resp = self._upload(app, "european.csv", content)
        self.assertEqual(resp.status_code, 200)

    def test_rejects_no_file(self):
        """No file in request → 400."""
        app = _make_app(self.tmp_dir)
        with app.test_client() as c:
            resp = c.post("/api/files/upload", data={}, content_type="multipart/form-data")
            self.assertEqual(resp.status_code, 400)

    def test_rejects_non_csv_extension(self):
        """File with .xlsx extension → 400."""
        app = _make_app(self.tmp_dir)
        content = b"col1,col2\n1,2\n"
        resp = self._upload(app, "data.xlsx", content)
        self.assertEqual(resp.status_code, 400)
