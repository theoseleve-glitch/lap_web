import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db.schema import PHASE_1_TABLES
from web.repos.reflection_repo import (
    upsert_reflection, get_reflection, replace_competitors, get_competitors,
)


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for _, sql in PHASE_1_TABLES:
        c.execute(sql)
    c.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'X')")
    c.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, session_date) "
        "VALUES ('s1', 'f.csv', 1, '2026-07-02')"
    )
    return c


def test_upsert_and_get_reflection_roundtrips_tags_as_list():
    c = _conn()
    upsert_reflection(c, "s1", {
        "result_tags": ["dnf", "traffic"],
        "driver_perceived_conditions": "damp",
        "felt_performance_rating": 7,
        "race_position": 3, "race_total_competitors": 12,
        "race_gap_to_leader_s": 8.4, "race_gap_to_nearest_s": 0.6,
        "race_laps_completed": 40, "race_is_dnf": True,
    })
    r = get_reflection(c, "s1")
    assert r["result_tags"] == ["dnf", "traffic"]
    assert r["driver_perceived_conditions"] == "damp"
    assert r["felt_performance_rating"] == 7
    assert r["race_is_dnf"] == 1
    assert r["race_position"] == 3


def test_get_reflection_empty_when_unset():
    c = _conn()
    r = get_reflection(c, "s1")
    assert r["result_tags"] == []
    assert r["felt_performance_rating"] is None


def test_replace_competitors_is_idempotent_replace():
    c = _conn()
    replace_competitors(c, "s1", [
        {"competitor_name": "A", "final_position": 1, "gap_to_this_driver_s": -2.0, "notes": ""},
        {"competitor_name": "B", "final_position": 2, "gap_to_this_driver_s": 0.5, "notes": "fought hard"},
    ])
    replace_competitors(c, "s1", [
        {"competitor_name": "C", "final_position": 1, "gap_to_this_driver_s": -1.0, "notes": ""},
    ])
    comps = get_competitors(c, "s1")
    assert [x["competitor_name"] for x in comps] == ["C"]
