"""Test annotation module."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from annotations import (
    create_annotation,
    delete_annotation,
    get_all_tags,
    get_annotation,
    get_annotations,
    search_annotations,
    update_annotation,
)


@pytest.fixture
def ann_db(test_db):
    conn = test_db
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'D1')")
    conn.execute("INSERT INTO tracks (track_id, track_name, lap_length_m) VALUES ('t1', 'T', 500)")
    conn.execute(
        "INSERT INTO sessions (session_id, csv_filename, driver_id, track_id, session_date) "
        "VALUES ('s1', 'x.csv', 1, 't1', '2024-01-01')"
    )
    conn.commit()
    return conn


class TestAnnotations:
    def test_create_and_get(self, ann_db):
        ann = create_annotation(ann_db, "s1", "Good turn 3", tags=["braking"])
        assert ann["id"] is not None
        fetched = get_annotation(ann_db, ann["id"])
        assert fetched["body"] == "Good turn 3"

    def test_update(self, ann_db):
        ann = create_annotation(ann_db, "s1", "Original")
        updated = update_annotation(ann_db, ann["id"], body="Updated")
        assert updated["body"] == "Updated"

    def test_delete(self, ann_db):
        ann = create_annotation(ann_db, "s1", "Remove me")
        assert delete_annotation(ann_db, ann["id"])
        assert get_annotation(ann_db, ann["id"]) is None

    def test_search(self, ann_db):
        create_annotation(ann_db, "s1", "Brake issue corner 5", tags=["braking"])
        create_annotation(ann_db, "s1", "Throttle note")
        results = search_annotations(ann_db, "brake")
        assert len(results) == 1

    def test_tags(self, ann_db):
        create_annotation(ann_db, "s1", "A", tags=["x", "y"])
        create_annotation(ann_db, "s1", "B", tags=["y", "z"])
        tags = get_all_tags(ann_db)
        assert set(tags) == {"x", "y", "z"}

    def test_empty_body_raises(self, ann_db):
        with pytest.raises(ValueError):
            create_annotation(ann_db, "s1", "")
