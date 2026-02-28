"""Tests for cycle_runner.py — inventory parsing, cycle creation, status updates."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cycle_runner import (
    create_cycle_file,
    find_next_pending,
    read_inventory,
    update_inventory_status,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INVENTORY = textwrap.dedent("""\
    # Feature Inventory

    | ID | Area | Feature | Tier | Test Method | Parity Ref | Status |
    |----|------|---------|------|-------------|------------|--------|
    | F-0001 | Auth | User registration | All | integration | — | passed |
    | F-0002 | Auth | Email validation | All | unit | — | pending |
    | F-0003 | Upload | CSV upload | All | integration | OK_R1 | pending |
""")


@pytest.fixture()
def inventory_file(tmp_path: Path) -> Path:
    """Write a sample inventory markdown file and return its path."""
    p = tmp_path / "feature-inventory.md"
    p.write_text(SAMPLE_INVENTORY, encoding="utf-8")
    return p


@pytest.fixture()
def cycle_template(tmp_path: Path) -> Path:
    """Write the cycle template into the expected location relative to ROOT."""
    # cycle_runner uses ROOT / "tools" / "cycle_template.md"
    # We'll monkeypatch ROOT instead — see individual tests
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    template = textwrap.dedent("""\
        # Cycle {cycle_number}: {feature_id} — {feature_name}

        **Date:** {date}
        **Tier:** {tier}
        **Area:** {area}
        **Test Method:** {test_method}

        ## Expected Behavior
        {expected_behavior}

        ## Parity Reference
        {parity_reference}

        ## Tests Executed
        - [ ] {test_list}
    """)
    (tools_dir / "cycle_template.md").write_text(template, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReadInventory:
    """Tests for read_inventory()."""

    def test_read_inventory(self, inventory_file: Path) -> None:
        """Parse a temp markdown file with 3 feature rows; verify all 7 fields."""
        features = read_inventory(str(inventory_file))

        assert len(features) == 3

        # First row
        assert features[0]["id"] == "F-0001"
        assert features[0]["area"] == "Auth"
        assert features[0]["feature"] == "User registration"
        assert features[0]["tier"] == "All"
        assert features[0]["test_method"] == "integration"
        assert features[0]["parity_ref"] == "\u2014"
        assert features[0]["status"] == "passed"

        # Second row
        assert features[1]["id"] == "F-0002"
        assert features[1]["area"] == "Auth"
        assert features[1]["feature"] == "Email validation"
        assert features[1]["status"] == "pending"

        # Third row
        assert features[2]["id"] == "F-0003"
        assert features[2]["area"] == "Upload"
        assert features[2]["feature"] == "CSV upload"
        assert features[2]["parity_ref"] == "OK_R1"
        assert features[2]["status"] == "pending"


class TestFindNextPending:
    """Tests for find_next_pending()."""

    def test_find_next_pending(self) -> None:
        """First=passed, second=pending -> returns second."""
        features = [
            {"id": "F-0001", "status": "passed"},
            {"id": "F-0002", "status": "pending"},
            {"id": "F-0003", "status": "pending"},
        ]
        result = find_next_pending(features)
        assert result is not None
        assert result["id"] == "F-0002"

    def test_find_next_pending_all_done(self) -> None:
        """All passed -> returns None."""
        features = [
            {"id": "F-0001", "status": "passed"},
            {"id": "F-0002", "status": "passed"},
        ]
        result = find_next_pending(features)
        assert result is None


class TestCreateCycleFile:
    """Tests for create_cycle_file()."""

    def test_create_cycle_file(self, cycle_template: Path, monkeypatch) -> None:
        """Create a cycle file in a temp dir; verify it exists and contains feature data."""
        import cycle_runner

        monkeypatch.setattr(cycle_runner, "ROOT", cycle_template)

        feature = {
            "id": "F-0042",
            "area": "Upload",
            "feature": "CSV upload via API",
            "tier": "All",
            "test_method": "integration",
            "parity_ref": "OK_R1",
            "status": "pending",
        }

        result_path = create_cycle_file(7, feature)

        assert Path(result_path).exists()

        content = Path(result_path).read_text(encoding="utf-8")
        assert "F-0042" in content
        assert "CSV upload via API" in content
        assert "Upload" in content
        assert "integration" in content
        assert "Cycle 7" in content

        # Verify filename format
        assert "CYCLE-0007.md" in result_path


class TestUpdateInventoryStatus:
    """Tests for update_inventory_status()."""

    def test_update_inventory_status(self, inventory_file: Path) -> None:
        """Update a feature's status and verify it changed in the file."""
        # Before: F-0002 is 'pending'
        features_before = read_inventory(str(inventory_file))
        f2_before = [f for f in features_before if f["id"] == "F-0002"][0]
        assert f2_before["status"] == "pending"

        # Update
        update_inventory_status("F-0002", "passed", str(inventory_file))

        # After: F-0002 should be 'passed'
        features_after = read_inventory(str(inventory_file))
        f2_after = [f for f in features_after if f["id"] == "F-0002"][0]
        assert f2_after["status"] == "passed"

        # Other rows unchanged
        f1 = [f for f in features_after if f["id"] == "F-0001"][0]
        assert f1["status"] == "passed"
        f3 = [f for f in features_after if f["id"] == "F-0003"][0]
        assert f3["status"] == "pending"
