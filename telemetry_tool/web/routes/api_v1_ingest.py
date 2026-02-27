"""v1 ingest aliases for analysis start/status endpoints."""

from flask import Blueprint

from .analysis import _analyze_start_impl, _analyze_status_impl

bp = Blueprint("api_v1_ingest", __name__, url_prefix="/api/v1/ingest")


@bp.route("/start", methods=["POST"])
def ingest_start_v1():
    """Canonical v1 alias for starting analysis ingest."""
    return _analyze_start_impl()


@bp.route("/status/<job_id>")
def ingest_status_v1(job_id: str):
    """Canonical v1 alias for polling analysis ingest status."""
    return _analyze_status_impl(job_id)
