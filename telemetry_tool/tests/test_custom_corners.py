"""Tests for custom corner geometry in the resume flow."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# 1. Schema tests
# ---------------------------------------------------------------------------

class TestResumeJobSchema:
    """Verify ResumeJobSchema accepts the new corners field."""

    def test_accepts_custom_corners(self):
        from web.schemas.jobs import ResumeJobSchema

        body = ResumeJobSchema(corners=[
            {"s_start": 100.0, "s_apex": 130.0, "s_end": 160.0},
            {"s_start": 300.0, "s_apex": 340.0, "s_end": 370.0},
        ])
        assert body.corners is not None
        assert len(body.corners) == 2
        assert body.corners[0].s_apex == 130.0

    def test_accepts_legacy_selected_corner_ids(self):
        from web.schemas.jobs import ResumeJobSchema

        body = ResumeJobSchema(selected_corner_ids=[1, 3, 5])
        assert body.selected_corner_ids == [1, 3, 5]
        assert body.corners is None

    def test_rejects_empty_body(self):
        from web.schemas.jobs import ResumeJobSchema

        with pytest.raises(ValidationError):
            ResumeJobSchema()

    def test_rejects_corner_with_start_after_end(self):
        from web.schemas.jobs import ResumeJobSchema

        with pytest.raises(ValidationError):
            ResumeJobSchema(corners=[
                {"s_start": 200.0, "s_apex": 130.0, "s_end": 100.0},
            ])

    def test_rejects_corner_with_apex_outside_range(self):
        from web.schemas.jobs import ResumeJobSchema

        with pytest.raises(ValidationError):
            ResumeJobSchema(corners=[
                {"s_start": 100.0, "s_apex": 50.0, "s_end": 160.0},
            ])


# ---------------------------------------------------------------------------
# 2. PipelineContext tests
# ---------------------------------------------------------------------------

class TestPipelineContext:
    """Verify PipelineContext handles custom_corners."""

    def test_set_and_serialize_custom_corners(self):
        from unittest.mock import MagicMock
        from pipeline_context import PipelineContext

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="test-job",
            workspace_id=1,
            session_id="sess-1",
            file_path="/tmp/test.csv",
        )

        corners = [
            {"s_start": 100.0, "s_apex": 130.0, "s_end": 160.0},
            {"s_start": 300.0, "s_apex": 340.0, "s_end": 370.0},
        ]
        ctx.set_custom_corners(corners)
        assert ctx.custom_corners == corners

        data = ctx._to_dict()
        assert data["custom_corners"] == corners

    def test_custom_corners_none_by_default(self):
        from unittest.mock import MagicMock
        from pipeline_context import PipelineContext

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="test-job",
            workspace_id=1,
            session_id="sess-1",
            file_path="/tmp/test.csv",
        )
        assert ctx.custom_corners is None


# ---------------------------------------------------------------------------
# 3. Enrich custom corners
# ---------------------------------------------------------------------------

class TestEnrichCustomCorners:
    """Verify enrich_custom_corners adds lat/lon/direction from track data."""

    def test_enriches_with_lat_lon(self):
        import numpy as np
        from pipeline.helpers import enrich_custom_corners

        lats = np.array([48.0, 48.0, 48.0, 47.999, 47.998])
        lons = np.array([2.0, 2.001, 2.002, 2.003, 2.003])
        dists = np.array([0.0, 100.0, 200.0, 300.0, 400.0])

        custom = [
            {"s_start": 50.0, "s_apex": 100.0, "s_end": 150.0},
            {"s_start": 250.0, "s_apex": 300.0, "s_end": 350.0},
        ]

        enriched = enrich_custom_corners(custom, lats, lons, dists)

        assert len(enriched) == 2
        assert enriched[0]["corner_id"] == 0
        assert enriched[1]["corner_id"] == 1
        assert enriched[0]["lat"] == pytest.approx(48.0, abs=0.01)
        assert enriched[0]["lon"] == pytest.approx(2.001, abs=0.001)
        assert "direction" in enriched[0]
        assert enriched[0]["s_start"] == 50.0
        assert enriched[0]["s_apex"] == 100.0
        assert enriched[0]["s_end"] == 150.0

    def test_empty_input(self):
        import numpy as np
        from pipeline.helpers import enrich_custom_corners

        result = enrich_custom_corners(
            [], np.array([48.0]), np.array([2.0]), np.array([0.0])
        )
        assert result == []


# ---------------------------------------------------------------------------
# 4. Finalize context tests
# ---------------------------------------------------------------------------

class TestFinalizeWithCustomCorners:
    """Verify custom_corners takes precedence."""

    def test_custom_corners_override_detected(self):
        from unittest.mock import MagicMock
        from pipeline_context import PipelineContext

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="test-job",
            workspace_id=1,
            session_id="sess-1",
            file_path="/tmp/test.csv",
        )

        custom = [
            {"s_start": 100.0, "s_apex": 130.0, "s_end": 160.0, "corner_id": 0},
        ]
        ctx.set_custom_corners(custom)

        assert ctx.custom_corners is not None
        assert ctx.selected_corner_ids is None

    def test_selected_ids_still_works(self):
        from unittest.mock import MagicMock
        from pipeline_context import PipelineContext

        mock_redis = MagicMock()
        ctx = PipelineContext.create(
            redis_client=mock_redis,
            job_id="test-job",
            workspace_id=1,
            session_id="sess-1",
            file_path="/tmp/test.csv",
        )

        ctx.set_selected_corner_ids([1, 3, 5])
        assert ctx.selected_corner_ids == [1, 3, 5]
        assert ctx.custom_corners is None


class TestEmptyCornerSelectionKeepsAllCorners:
    """The bug that emptied every corner surface in production.

    The upload page posts `{selected_corner_ids: []}` meaning "auto-accept
    the detected corners". The backend read `[] is not None` as a real
    selection, matched nothing, and discarded all of them -- while the job
    still reported status "ok". Every session in production carried zero
    corner_metrics as a result.
    """

    @staticmethod
    def _corners():
        return [{"corner_id": i, "s_start": i * 100.0} for i in range(6)]

    def test_empty_list_keeps_every_detected_corner(self):
        from tasks.pipeline_tasks import _apply_corner_selection
        out = _apply_corner_selection([], self._corners())
        assert [c["corner_id"] for c in out] == [0, 1, 2, 3, 4, 5]

    def test_none_keeps_every_detected_corner(self):
        from tasks.pipeline_tasks import _apply_corner_selection
        out = _apply_corner_selection(None, self._corners())
        assert len(out) == 6

    def test_a_real_selection_still_filters(self):
        from tasks.pipeline_tasks import _apply_corner_selection
        out = _apply_corner_selection([1, 3, 5], self._corners())
        assert [c["corner_id"] for c in out] == [1, 3, 5]

    def test_a_selection_naming_unknown_ids_yields_nothing(self):
        # An explicit, non-empty selection is honoured literally even when it
        # matches nothing -- that is a caller error, not the empty-means-all
        # case, and must stay distinguishable from it.
        from tasks.pipeline_tasks import _apply_corner_selection
        out = _apply_corner_selection([99], self._corners())
        assert out == []

    def test_no_detected_corners_stays_empty(self):
        from tasks.pipeline_tasks import _apply_corner_selection
        assert _apply_corner_selection([], []) == []
        assert _apply_corner_selection([1, 2], []) == []
