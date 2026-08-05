"""Grip anchor — schema, stage wiring and persistence."""
import numpy as np
import pandas as pd
import pytest


def test_corner_metrics_has_the_grip_anchor_columns(test_db):
    """The pytest fixture builds from db/schema.py, so a column that exists
    only in Alembic is invisible here — and therefore untestable."""
    cur = test_db.execute("SELECT * FROM corner_metrics LIMIT 0")
    cols = {d[0] for d in cur.description}

    assert "grip_anchor_tier" in cols
    assert "grip_anchor_reason" in cols
    assert "grip_anchor_pct" in cols
    assert "grip_anchor_baseline_g" in cols


def test_insert_corner_metric_carries_the_anchor_columns():
    from db.queries import INSERT_CORNER_METRIC

    for col in (
        "grip_anchor_tier", "grip_anchor_reason",
        "grip_anchor_pct", "grip_anchor_baseline_g",
    ):
        assert col in INSERT_CORNER_METRIC, f"{col} missing from the INSERT"
        assert f":{col}" in INSERT_CORNER_METRIC, f":{col} bind param missing"
