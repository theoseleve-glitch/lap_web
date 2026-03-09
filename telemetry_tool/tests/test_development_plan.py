"""Test development plan module."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from development_plan import (
    create_custom_plan,
    create_plan_from_template,
    delete_plan,
    get_plan,
    get_plan_completion_pct,
    get_plan_templates,
    get_plans,
    update_plan_progress,
)


@pytest.fixture
def plan_db(test_db):
    conn = test_db
    conn.execute("INSERT INTO drivers (driver_id, driver_name) VALUES (1, 'D1')")
    conn.commit()
    return conn


class TestDevPlans:
    def test_five_templates(self):
        assert len(get_plan_templates()) == 5

    def test_all_templates_have_4_weeks(self):
        for t in get_plan_templates():
            assert t["n_weeks"] == 4
            assert t["n_drills"] >= 12

    def test_create_from_template(self, plan_db):
        plan = create_plan_from_template(plan_db, 1, "beginner")
        assert plan["level"] == "beginner"
        assert plan["completion_pct"] == 0.0

    def test_progress_tracking(self, plan_db):
        plan = create_plan_from_template(plan_db, 1, "beginner")
        updated = update_plan_progress(plan_db, plan["id"], 0, 0, True)
        assert updated["progress"][0][0] is True
        assert updated["completion_pct"] > 0

    def test_full_completion(self, plan_db):
        plan = create_plan_from_template(plan_db, 1, "beginner")
        for wi, week in enumerate(plan["progress"]):
            for di in range(len(week)):
                update_plan_progress(plan_db, plan["id"], wi, di, True)
        final = get_plan(plan_db, plan["id"])
        assert final["completion_pct"] == 100.0

    def test_bad_template_raises(self, plan_db):
        with pytest.raises(ValueError):
            create_plan_from_template(plan_db, 1, "nonexistent")

    def test_bounds_check(self, plan_db):
        plan = create_plan_from_template(plan_db, 1, "beginner")
        with pytest.raises(IndexError):
            update_plan_progress(plan_db, plan["id"], 99, 0)
