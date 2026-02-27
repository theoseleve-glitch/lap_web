from flask import Flask

from web.routes.analysis import bp as analysis_bp
from web.routes.api_v1_ingest import bp as api_v1_ingest_bp


def test_ingest_v1_aliases_share_handler_behavior(tmp_path):
    app = Flask(__name__)
    app.config["DATA_RAW_DIR"] = str(tmp_path)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(api_v1_ingest_bp)

    client = app.test_client()

    legacy = client.post("/analyze/api/start", data={})
    v1 = client.post("/api/v1/ingest/start", data={})

    assert legacy.status_code == 400
    assert v1.status_code == 400
    assert legacy.get_json() == v1.get_json()

    missing_legacy = client.get("/analyze/api/status/missing")
    missing_v1 = client.get("/api/v1/ingest/status/missing")

    assert missing_legacy.status_code == 404
    assert missing_v1.status_code == 404
    assert missing_legacy.get_json() == missing_v1.get_json()
