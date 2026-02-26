"""Tests for pipeline_version module — version constant and is_stale()."""

from pipeline_version import PIPELINE_VERSION, is_stale


class TestPipelineVersion:
    def test_is_int(self):
        assert isinstance(PIPELINE_VERSION, int)

    def test_positive(self):
        assert PIPELINE_VERSION > 0

    def test_current_value(self):
        assert PIPELINE_VERSION == 1


class TestIsStale:
    def test_none_is_stale(self):
        """None should be treated as version 0, which is older than 1."""
        assert is_stale(None) is True

    def test_zero_is_stale(self):
        assert is_stale(0) is True

    def test_older_version_is_stale(self):
        """Any version less than PIPELINE_VERSION is stale."""
        assert is_stale(PIPELINE_VERSION - 1) is True

    def test_current_version_not_stale(self):
        assert is_stale(PIPELINE_VERSION) is False

    def test_newer_version_not_stale(self):
        assert is_stale(PIPELINE_VERSION + 1) is False

    def test_far_older_version(self):
        assert is_stale(-5) is True

    def test_far_newer_version(self):
        assert is_stale(999) is False
