"""SEO health check — validates route metadata completeness."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

bp = Blueprint("seo_health", __name__, url_prefix="/api/v1/seo")

_ROUTE_MAP_PATH = (
    Path(__file__).resolve().parents[3] / "lap-website" / "src" / "data" / "route-map.ts"
)


def _parse_route_map() -> dict:
    """Extract route entries from route-map.ts (naive regex parse)."""
    if not _ROUTE_MAP_PATH.exists():
        return {}
    text = _ROUTE_MAP_PATH.read_text(encoding="utf-8")
    routes: dict = {}
    for match in re.finditer(r"'(/[^']*)':\s*\{([^}]+)\}", text):
        path = match.group(1)
        block = match.group(2)
        entry: dict = {"path": path}
        for field in ("title", "primaryKeyword", "metaDescription", "ogTitle", "ogDescription"):
            field_match = re.search(rf"{field}:\s*'([^']*)'", block)
            if field_match:
                entry[field] = field_match.group(1)
        entry["noIndex"] = "noIndex: true" in block
        routes[path] = entry
    return routes


@bp.route("/health", methods=["GET"])
def seo_health():
    """Return SEO completeness report for marketing routes."""
    routes = _parse_route_map()
    marketing = {k: v for k, v in routes.items() if not v.get("noIndex")}
    total = len(marketing)
    missing_meta = [k for k, v in marketing.items() if not v.get("metaDescription")]
    missing_keyword = [k for k, v in marketing.items() if not v.get("primaryKeyword")]
    missing_og = [k for k, v in marketing.items() if not v.get("ogTitle") and not v.get("ogDescription")]
    return jsonify({
        "ok": True,
        "data": {
            "total_marketing_routes": total,
            "routes_with_meta": total - len(missing_meta),
            "routes_missing_meta": missing_meta,
            "routes_missing_keyword": missing_keyword,
            "routes_missing_og": missing_og,
        },
    }), 200
