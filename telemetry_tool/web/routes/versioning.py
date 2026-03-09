"""Processing versioning API routes — stale sessions + pipeline version.

Provides endpoints for identifying sessions processed with an older
pipeline version and retrieving the current pipeline version number.
All endpoints are workspace-scoped via ``g.workspace_id``.
"""

from __future__ import annotations

import logging

from flask import Blueprint, g
from sqlalchemy import text

from pipeline_version import PIPELINE_VERSION
from web.api_utils import api_response
from web.rate_limit import rate_limit
from web.schemas.common import PaginationParams
from web.validation import validate_params

logger = logging.getLogger(__name__)

bp = Blueprint("versioning", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_pg_connection():
    """Return a PG connection via the web.db_pg module."""
    from web.db_pg import get_pg_connection as _get_pg

    return _get_pg()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@bp.route("/sessions/stale", methods=["GET"])
@rate_limit(tier="read")
@validate_params(PaginationParams)
def stale_sessions():
    """List sessions with a processing_version older than the current pipeline.

    Returns:
        200 with ``{"current_version": N, "stale_sessions": [...], "count": N}``
    """
    conn = get_pg_connection()
    cursor = conn.execute(
        text(
            "SELECT session_id, processing_version FROM sessions "
            "WHERE workspace_id = :ws "
            "AND (processing_version IS NULL OR processing_version < :version)"
        ),
        {"ws": g.workspace_id, "version": PIPELINE_VERSION},
    )
    rows = cursor.fetchall()
    stale = [dict(r) if not isinstance(r, dict) else r for r in rows]

    return api_response({
        "current_version": PIPELINE_VERSION,
        "stale_sessions": stale,
        "count": len(stale),
    })


@bp.route("/pipeline/version", methods=["GET"])
@rate_limit(tier="read")
def pipeline_version():
    """Return the current pipeline processing version.

    Returns:
        200 with ``{"pipeline_version": N, "pipeline_version_full": "vN-hash"}``
    """
    from pipeline_version import full_version_string

    return api_response({
        "pipeline_version": PIPELINE_VERSION,
        "pipeline_version_full": full_version_string(),
    })
