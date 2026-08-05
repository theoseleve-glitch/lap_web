"""Driving events — schema, persistence, stage wiring and real-data acceptance."""
import numpy as np
import pandas as pd
import pytest


def test_driving_events_table_exists_with_the_expected_columns(test_db):
    cur = test_db.execute("SELECT * FROM driving_events LIMIT 0")
    cols = {d[0] for d in cur.description}

    for c in (
        "session_id", "lap_number", "corner_id", "event_type",
        "s_norm_start", "s_norm_end",
        "magnitude", "magnitude_unit",
        "time_cost_s", "validity", "reason",
        "n_samples_in_window", "evidence_json",
    ):
        assert c in cols, f"{c} missing from driving_events"


def test_driving_events_has_a_unique_key_so_reprocess_does_not_double(test_db):
    """Without this, every reprocess doubles the table."""
    row = dict(
        session_id="s1", lap_number=1, corner_id=1, event_type="over_slowing",
        s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4, magnitude_unit="m/s",
        time_cost_s=0.31, validity="measured", reason=None,
        n_samples_in_window=42, evidence_json="{}",
    )
    cols = ", ".join(row)
    binds = ", ".join(f":{k}" for k in row)
    sql = f"INSERT OR REPLACE INTO driving_events ({cols}) VALUES ({binds})"

    test_db.execute(sql, row)
    test_db.execute(sql, row)
    test_db.commit()

    n = test_db.execute(
        "SELECT count(*) FROM driving_events WHERE session_id='s1'"
    ).fetchone()[0]
    assert n == 1, "reprocess duplicated the row -- unique key missing"


def test_driving_events_is_registered_for_retention_and_gdpr():
    """Data that cannot be purged or exported is a compliance defect."""
    from tasks import retention_tasks
    import inspect
    from tasks import gdpr_tasks

    assert "driving_events" in retention_tasks._RAW_DATA_TABLES
    assert "driving_events" in inspect.getsource(gdpr_tasks)
