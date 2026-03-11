"""Tests for CauseTaxonomy — JSON loading, Pydantic validation, lookup."""
import pytest
from telemetry_tool.coaching.taxonomy.causes import CauseTaxonomy


class TestCauseTaxonomyLoading:
    def test_loads_all_categories(self):
        tax = CauseTaxonomy()
        assert "braking" in tax.categories
        assert "cornering" in tax.categories
        assert "exit" in tax.categories
        assert "consistency" in tax.categories
        assert "vehicle_management" in tax.categories

    def test_braking_has_seven_causes(self):
        tax = CauseTaxonomy()
        assert len(tax.categories["braking"]) == 7

    def test_each_cause_has_required_fields(self):
        tax = CauseTaxonomy()
        for cat_name, causes in tax.categories.items():
            for cause_id, cause in causes.items():
                assert "symptom" in cause, f"{cat_name}.{cause_id} missing symptom"
                assert "diagnosis" in cause, f"{cat_name}.{cause_id} missing diagnosis"
                assert "root_cause" in cause, f"{cat_name}.{cause_id} missing root_cause"
                assert cause["root_cause"] in (
                    "technique", "confidence", "line", "balance",
                    "aggression", "fitness", "management", "awareness", "fear"
                ), f"{cat_name}.{cause_id} invalid root_cause: {cause['root_cause']}"


class TestCauseTaxonomyLookup:
    def test_get_cause(self):
        tax = CauseTaxonomy()
        cause = tax.get_cause("early_braking_confidence")
        assert cause is not None
        assert cause["root_cause"] in ("confidence", "fear")

    def test_get_cause_unknown_returns_none(self):
        tax = CauseTaxonomy()
        assert tax.get_cause("nonexistent_cause") is None

    def test_get_category_for_cause(self):
        tax = CauseTaxonomy()
        assert tax.get_category("early_apex") == "cornering"
        assert tax.get_category("late_throttle_application") == "exit"

    def test_get_severity(self):
        tax = CauseTaxonomy()
        sev = tax.get_severity("early_braking_confidence", delta=7.0)
        assert sev in ("mild", "moderate", "severe")

    def test_get_severity_mild(self):
        tax = CauseTaxonomy()
        sev = tax.get_severity("early_braking_confidence", delta=3.0)
        assert sev == "mild"

    def test_get_severity_severe(self):
        tax = CauseTaxonomy()
        sev = tax.get_severity("early_braking_confidence", delta=25.0)
        assert sev == "severe"


class TestCauseTaxonomyValidation:
    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"version": 2, "categories": {"braking": {"causes": {"x": {}}}}}')
        with pytest.raises(ValueError):
            CauseTaxonomy(path=str(bad))
