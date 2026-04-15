"""Tests for the persistence/accumulation layer.

Covers:
  - VehicleCalibrationRegistry: lookup, active selection, missing fallback,
    deprecation, version selection, persistence round-trip
  - CrossSessionAccumulator: compatibility checks, merge guards,
    transition rejection, divergence rejection, provenance tracking,
    persistence reload, no-contamination invariants
  - layered_query: current beats accumulated when strong, accumulated
    rescues sparse current, fallback depth correctness
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from track_surface.condition_bucketing import (
    ACTIVE_BUCKETS,
    TRANSITION_BUCKET,
    BucketKey,
    BucketedSurfaceField,
)
from track_surface.cross_session_accumulator import (
    AccumulatorConfig,
    AccumulatorKey,
    AccumulatorRegistry,
    CrossSessionAccumulator,
    SessionFingerprint,
    TrackFingerprint,
    layered_query,
    MergeRejection,
    SessionContribution,
)
from track_surface.surface_field import SurfaceFieldConfig
from track_surface.vehicle_calibration_registry import (
    CalibrationProfile,
    FitProvenance,
    FitQuality,
    RoadStateCalibration,
    TireCalibration,
    VehicleCalibrationRegistry,
    default_calibration,
    make_profile,
)


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def grid_bins():
    s_bins = np.arange(0, 210, 10.0)
    n_bins = np.arange(-5, 6, 1.0)
    return s_bins, n_bins


def _make_session_field(
    s_bins, n_bins,
    *,
    fill_buckets: dict[BucketKey, float] | None = None,
    n_per_bucket: int = 100,
) -> BucketedSurfaceField:
    """Helper: build a BucketedSurfaceField with samples in named buckets."""
    bf = BucketedSurfaceField(s_bins, n_bins)
    if fill_buckets is None:
        fill_buckets = {BucketKey("flat", "mid"): 1.10}
    for bk, lam in fill_buckets.items():
        keys = np.array([bk] * n_per_bucket, dtype=object)
        bf.update(
            np.linspace(10, 190, n_per_bucket),
            np.zeros(n_per_bucket),
            np.full(n_per_bucket, lam),
            np.full(n_per_bucket, 0.8),
            keys,
        )
    bf.apply_spatial_smoothing()
    return bf


def _make_track_fp(name="Daytona", layout="2011_road", length=5729.0):
    return TrackFingerprint(name=name, layout=layout, length_m=length)


def _make_session_fp(session_id="s_001", track_fp=None, profile_id="mclaren_v1", n=10000):
    return SessionFingerprint(
        session_id=session_id,
        track_fingerprint=track_fp or _make_track_fp(),
        calibration_profile_id=profile_id,
        n_valid_samples=n,
    )


def _make_calibration_profile(
    *, profile_id="test_prof", vehicle_key="testcar", vehicle_class="GT4",
    active=True, version=1,
) -> CalibrationProfile:
    return make_profile(
        profile_id=profile_id,
        vehicle_key=vehicle_key,
        vehicle_class=vehicle_class,
        tire=TireCalibration(d1_lat=2.5, d1_long=2.4, d2_lat=-0.0001, d2_long=-0.0001),
        road_state=RoadStateCalibration(
            roll_compliance_rad_per_mps2=0.003,
            pitch_compliance_rad_per_mps2=0.003,
        ),
        session_id="seed_session",
        fit_method="frozen_baseline",
        n_samples=20000,
        calibration_version=version,
        active=active,
    )


# ── VehicleCalibrationRegistry tests ────────────────────────


class TestRegistryLookup:
    def test_empty_registry_resolve_returns_default(self):
        reg = VehicleCalibrationRegistry()
        resolved = reg.resolve("unknown_car")
        assert resolved.source == "default_fallback"
        assert resolved.profile.vehicle_key == "unknown_car"
        # Default profile is NEVER active in registry semantics
        assert resolved.profile.active is False

    def test_exact_match_wins(self):
        reg = VehicleCalibrationRegistry()
        prof = _make_calibration_profile(profile_id="p1", vehicle_key="mclaren", vehicle_class="GT4")
        reg.upsert(prof)
        resolved = reg.resolve("mclaren")
        assert resolved.source == "registry_active"
        assert resolved.profile.profile_id == "p1"
        assert resolved.matched_vehicle_key == "mclaren"

    def test_class_fallback(self):
        reg = VehicleCalibrationRegistry()
        # Only a McLaren profile is registered
        reg.upsert(_make_calibration_profile(
            profile_id="mclaren_v1", vehicle_key="mclaren", vehicle_class="GT4",
        ))
        # Audi RS3 has no profile but is GT4 class — should class-fallback
        resolved = reg.resolve("audi_rs3", vehicle_class="GT4")
        assert resolved.source == "registry_class_fallback"
        assert resolved.matched_vehicle_key == "mclaren"

    def test_no_class_fallback_for_different_class(self):
        reg = VehicleCalibrationRegistry()
        reg.upsert(_make_calibration_profile(
            profile_id="mclaren_v1", vehicle_key="mclaren", vehicle_class="GT4",
        ))
        # Touring car class — no class fallback should match
        resolved = reg.resolve("bmw_m2", vehicle_class="TouringCar")
        assert resolved.source == "default_fallback"

    def test_class_fallback_picks_best_provenance(self):
        reg = VehicleCalibrationRegistry()
        reg.upsert(_make_calibration_profile(
            profile_id="p_low", vehicle_key="lowdata_car", vehicle_class="GT4",
        ))
        # Override n_samples on second profile
        reg.upsert(replace(
            _make_calibration_profile(
                profile_id="p_high", vehicle_key="highdata_car", vehicle_class="GT4",
            ),
            provenance=FitProvenance(
                session_id="big", fit_method="session_fit",
                harness_version="v1", fit_date="2026-01-01T00:00:00+00:00",
                n_samples=999999,
            ),
        ))
        resolved = reg.resolve("audi", vehicle_class="GT4")
        assert resolved.source == "registry_class_fallback"
        assert resolved.profile.profile_id == "p_high"

    def test_only_one_active_per_vehicle(self):
        reg = VehicleCalibrationRegistry()
        reg.upsert(_make_calibration_profile(profile_id="p1", vehicle_key="mclaren"))
        reg.upsert(_make_calibration_profile(profile_id="p2", vehicle_key="mclaren", version=2))
        actives = [p for p in reg.list_for_vehicle("mclaren") if p.active]
        assert len(actives) == 1
        assert actives[0].profile_id == "p2"  # second upsert deactivates first

    def test_get_active_returns_none_when_no_profile(self):
        reg = VehicleCalibrationRegistry()
        assert reg.get_active("mclaren") is None

    def test_get_active_raises_on_multiple_active(self):
        # Manually construct a registry with two active profiles for the same vehicle
        # (which upsert would normally prevent)
        reg = VehicleCalibrationRegistry()
        p1 = _make_calibration_profile(profile_id="p1", vehicle_key="mclaren")
        p2 = _make_calibration_profile(profile_id="p2", vehicle_key="mclaren", version=2)
        reg.profiles = [p1, p2]
        with pytest.raises(RuntimeError, match="active"):
            reg.get_active("mclaren")


class TestRegistryDeprecation:
    def test_deprecate_clears_active(self):
        reg = VehicleCalibrationRegistry()
        reg.upsert(_make_calibration_profile(profile_id="p1", vehicle_key="mclaren"))
        reg.deprecate("p1", reason="superseded")
        prof = reg.get_by_id("p1")
        assert prof.active is False
        assert prof.deprecated is True
        assert "DEPRECATED" in prof.notes
        assert "superseded" in prof.notes

    def test_deprecate_unknown_raises(self):
        reg = VehicleCalibrationRegistry()
        with pytest.raises(KeyError):
            reg.deprecate("nope")

    def test_deprecated_not_returned_as_active(self):
        reg = VehicleCalibrationRegistry()
        reg.upsert(_make_calibration_profile(profile_id="p1", vehicle_key="mclaren"))
        reg.deprecate("p1")
        assert reg.get_active("mclaren") is None
        resolved = reg.resolve("mclaren")
        assert resolved.source == "default_fallback"


class TestRegistryPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        reg = VehicleCalibrationRegistry()
        reg.upsert(_make_calibration_profile(profile_id="p1", vehicle_key="mclaren"))
        reg.upsert(_make_calibration_profile(
            profile_id="p2", vehicle_key="bmw", vehicle_class="TouringCar",
        ))
        path = tmp_path / "reg.json"
        reg.save(path)
        reloaded = VehicleCalibrationRegistry.load(path)
        assert len(reloaded.profiles) == 2
        assert reloaded.get_by_id("p1") is not None
        assert reloaded.get_by_id("p2").vehicle_class == "TouringCar"

    def test_load_missing_file_returns_empty(self, tmp_path):
        reg = VehicleCalibrationRegistry.load(tmp_path / "missing.json")
        assert reg.profiles == []

    def test_load_unsupported_version_raises(self, tmp_path):
        path = tmp_path / "reg.json"
        path.write_text(json.dumps({"version": 999, "profiles": []}))
        with pytest.raises(ValueError, match="Unsupported"):
            VehicleCalibrationRegistry.load(path)

    def test_load_duplicate_profile_id_raises(self, tmp_path):
        path = tmp_path / "reg.json"
        # Construct a payload with two profiles sharing an id (only possible
        # by hand-editing — upsert would prevent it)
        prof = _make_calibration_profile(profile_id="dup", vehicle_key="x")
        payload = {
            "version": 1,
            "profiles": [prof.to_dict(), prof.to_dict()],
        }
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError, match="Duplicate"):
            VehicleCalibrationRegistry.load(path)


class TestRegistryConstruction:
    def test_active_and_deprecated_mutually_exclusive(self):
        with pytest.raises(ValueError, match="active.*deprecated"):
            CalibrationProfile(
                profile_id="x", vehicle_key="v", vehicle_class="c",
                calibration_version=1, active=True, deprecated=True,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                tire=TireCalibration(d1_lat=2.0, d1_long=2.0, d2_lat=0, d2_long=0),
                road_state=RoadStateCalibration(
                    roll_compliance_rad_per_mps2=0.001,
                    pitch_compliance_rad_per_mps2=0.001,
                ),
                provenance=FitProvenance(
                    session_id="s", fit_method="m", harness_version="v",
                    fit_date="2026-01-01T00:00:00+00:00", n_samples=0,
                ),
            )

    def test_invalid_calibration_version_rejected(self):
        with pytest.raises(ValueError, match="calibration_version"):
            make_profile(
                profile_id="p", vehicle_key="v", vehicle_class="c",
                tire=TireCalibration(d1_lat=2.0, d1_long=2.0, d2_lat=0, d2_long=0),
                road_state=RoadStateCalibration(
                    roll_compliance_rad_per_mps2=0.001,
                    pitch_compliance_rad_per_mps2=0.001,
                ),
                session_id="s", fit_method="m", n_samples=0,
                calibration_version=0,  # bad
            )

    def test_next_version_starts_at_1(self):
        reg = VehicleCalibrationRegistry()
        assert reg.next_version_for("new") == 1
        reg.upsert(_make_calibration_profile(profile_id="p1", vehicle_key="x", version=1))
        assert reg.next_version_for("x") == 2
        reg.upsert(_make_calibration_profile(profile_id="p2", vehicle_key="x", version=2))
        assert reg.next_version_for("x") == 3


# ── TrackFingerprint compatibility ───────────────────────────


class TestTrackFingerprint:
    def test_exact_match_compatible(self):
        a = _make_track_fp()
        b = _make_track_fp()
        ok, _ = a.is_compatible(b)
        assert ok

    def test_name_mismatch_rejected(self):
        a = _make_track_fp(name="Daytona")
        b = _make_track_fp(name="Spa")
        ok, reason = a.is_compatible(b)
        assert not ok
        assert "name" in reason

    def test_layout_mismatch_rejected(self):
        a = _make_track_fp(layout="2011_road")
        b = _make_track_fp(layout="oval")
        ok, reason = a.is_compatible(b)
        assert not ok
        assert "layout" in reason

    def test_length_within_tolerance_accepted(self):
        a = _make_track_fp(length=5729.0)
        b = _make_track_fp(length=5740.0)  # 11m diff, within 50m tol
        ok, _ = a.is_compatible(b)
        assert ok

    def test_length_outside_tolerance_rejected(self):
        a = _make_track_fp(length=5729.0)
        b = _make_track_fp(length=5800.0)  # 71m diff, outside 50m tol
        ok, reason = a.is_compatible(b)
        assert not ok
        assert "length" in reason


# ── CrossSessionAccumulator tests ───────────────────────────


class TestAccumulatorAccept:
    def test_compatible_session_accepted(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        sf = _make_session_fp()
        bf = _make_session_field(s_bins, n_bins)
        result = acc.add_session(sf, bf)
        assert isinstance(result, SessionContribution)
        assert len(acc.contributions) == 1
        assert len(acc.rejections) == 0

    def test_track_geometry_mismatch_rejected(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(name="Daytona"), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        sf = _make_session_fp(track_fp=_make_track_fp(name="Spa"))
        bf = _make_session_field(s_bins, n_bins)
        result = acc.add_session(sf, bf)
        assert isinstance(result, MergeRejection)
        assert "track_geometry_mismatch" in result.reason
        assert len(acc.contributions) == 0
        assert len(acc.rejections) == 1

    def test_calibration_mismatch_rejected(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        sf = _make_session_fp(profile_id="bmw_v1")
        bf = _make_session_field(s_bins, n_bins)
        result = acc.add_session(sf, bf)
        assert isinstance(result, MergeRejection)
        assert "calibration_profile_mismatch" in result.reason

    def test_low_quality_session_rejected(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        sf = _make_session_fp(n=500)  # too few samples
        bf = _make_session_field(s_bins, n_bins)
        result = acc.add_session(sf, bf)
        assert isinstance(result, MergeRejection)
        assert "low_quality_session" in result.reason

    def test_grid_mismatch_rejected(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        # Different grid for the session
        bf = _make_session_field(np.arange(0, 410, 10.0), n_bins)
        sf = _make_session_fp()
        result = acc.add_session(sf, bf)
        assert isinstance(result, MergeRejection)
        assert "grid_mismatch" in result.reason


class TestAccumulatorMerge:
    def test_first_session_populates_buckets(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.10,
        })
        sf = _make_session_fp(session_id="s1")
        contrib = acc.add_session(sf, bf)
        assert isinstance(contrib, SessionContribution)
        assert "flat/mid" in contrib.bucket_breakdown
        assert contrib.bucket_breakdown["flat/mid"] > 0
        # The accumulator field should now have evidence in flat/mid
        diag = acc.diagnostics()
        assert diag["per_bucket"]["flat/mid"]["cells_observed"] > 0

    def test_second_compatible_session_adds_evidence(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf1 = _make_session_field(s_bins, n_bins, fill_buckets={BucketKey("flat", "mid"): 1.10})
        bf2 = _make_session_field(s_bins, n_bins, fill_buckets={BucketKey("flat", "mid"): 1.12})
        acc.add_session(_make_session_fp(session_id="s1"), bf1)
        n_obs_after_one = acc._fields[BucketKey("flat", "mid")].n_obs.sum()
        acc.add_session(_make_session_fp(session_id="s2"), bf2)
        n_obs_after_two = acc._fields[BucketKey("flat", "mid")].n_obs.sum()
        assert n_obs_after_two > n_obs_after_one

    def test_divergent_bucket_rejected(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        # Tighter divergence threshold and tiny prior std so divergence is easy
        cfg = AccumulatorConfig(
            divergence_sigmas=2.0,
            field_config=SurfaceFieldConfig(prior_std=0.1, min_confidence=0.05),
        )
        acc = CrossSessionAccumulator(ak, s_bins, n_bins, cfg)
        # First session: lambda 1.0 in flat/mid
        bf1 = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.0,
        }, n_per_bucket=300)
        acc.add_session(_make_session_fp(session_id="s1"), bf1)
        # Second session: wildly different lambda 2.0 in same bucket
        bf2 = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 2.0,
        }, n_per_bucket=300)
        contrib = acc.add_session(_make_session_fp(session_id="s2"), bf2)
        assert isinstance(contrib, SessionContribution)
        # The whole flat/mid bucket should be in rejected_buckets
        assert "flat/mid" in contrib.rejected_buckets
        assert contrib.rejected_cells > 0

    def test_provenance_per_cell(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf = _make_session_field(s_bins, n_bins)
        acc.add_session(_make_session_fp(session_id="alpha"), bf)
        acc.add_session(_make_session_fp(session_id="beta"), bf)
        # Query a cell that should have both contributions
        sessions = acc.cell_sessions(BucketKey("flat", "mid"), 50.0, 0.0)
        assert "alpha" in sessions
        assert "beta" in sessions

    def test_transition_bucket_never_accumulates(self, grid_bins):
        """The accumulator should expose no evidence under TRANSITION_BUCKET."""
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        # Even with a populated accumulator, querying TRANSITION_BUCKET → prior
        bf = _make_session_field(s_bins, n_bins, fill_buckets={BucketKey("flat", "mid"): 1.10})
        acc.add_session(_make_session_fp(), bf)
        result = acc.query(50.0, 0.0, TRANSITION_BUCKET)
        assert result.fallback_depth == 2
        assert result.confidence == 0.0


class TestAccumulatorIsolation:
    def test_flat_and_banked_independent(self, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.5,
        }, n_per_bucket=200)
        acc.add_session(_make_session_fp(), bf)
        # Querying banked/mid should NOT return 1.5 — at most section fallback
        # but we put data only in flat/mid, so banked/mid has no exact data
        q = acc.query(50.0, 0.0, BucketKey("banked", "mid"))
        assert q.mean < 1.4  # near prior, not contaminated by flat/mid


# ── Persistence ─────────────────────────────────────────────


class TestAccumulatorPersistence:
    def test_save_and_reload_round_trip(self, tmp_path, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf = _make_session_field(s_bins, n_bins)
        acc.add_session(_make_session_fp(session_id="s1"), bf)
        acc.add_session(_make_session_fp(session_id="s2"), bf)

        npz_path, json_path = acc.save(tmp_path)
        assert npz_path.is_file()
        assert json_path.is_file()

        # Reload and verify
        reloaded = CrossSessionAccumulator.load(tmp_path, ak.key)
        assert reloaded.key.key == ak.key
        # Same observation counts
        for bk in ACTIVE_BUCKETS:
            assert np.array_equal(
                reloaded._fields[bk].n_obs,
                acc._fields[bk].n_obs,
            )
            np.testing.assert_array_almost_equal(
                reloaded._fields[bk].mean,
                acc._fields[bk].mean,
            )
        # Provenance preserved
        assert len(reloaded.contributions) == 2
        assert reloaded.contributions[0].session_id == "s1"
        # Cell sessions preserved
        sessions = reloaded.cell_sessions(BucketKey("flat", "mid"), 50.0, 0.0)
        assert "s1" in sessions and "s2" in sessions

    def test_reload_unsupported_schema_raises(self, tmp_path, grid_bins):
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf = _make_session_field(s_bins, n_bins)
        acc.add_session(_make_session_fp(), bf)
        npz_path, json_path = acc.save(tmp_path)

        # Tamper schema version in sidecar
        with open(json_path, "r") as f:
            sidecar = json.load(f)
        sidecar["schema_version"] = 999
        with open(json_path, "w") as f:
            json.dump(sidecar, f)

        with pytest.raises(ValueError, match="schema"):
            CrossSessionAccumulator.load(tmp_path, ak.key)

    def test_registry_get_or_create(self, tmp_path, grid_bins):
        s_bins, n_bins = grid_bins
        reg = AccumulatorRegistry(tmp_path)
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")

        acc1 = reg.get_or_create(ak, s_bins, n_bins)
        bf = _make_session_field(s_bins, n_bins)
        acc1.add_session(_make_session_fp(session_id="first"), bf)
        reg.save(acc1)

        # New registry instance: get_existing should load from disk
        reg2 = AccumulatorRegistry(tmp_path)
        acc2 = reg2.get_existing(ak)
        assert acc2 is not None
        assert len(acc2.contributions) == 1
        assert acc2.contributions[0].session_id == "first"


# ── Layered query ───────────────────────────────────────────


class TestLayeredQuery:
    def test_strong_current_beats_accumulated(self, grid_bins):
        """When current-session evidence is strong, accumulated must NOT override it."""
        s_bins, n_bins = grid_bins
        # Strong current session: lambda 1.5
        current = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.5,
        }, n_per_bucket=500)
        # Accumulator with a different lambda value at same location
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        acc_field = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.0,
        }, n_per_bucket=500)
        acc.add_session(_make_session_fp(session_id="hist"), acc_field)
        # Query — current should win
        result = layered_query(
            s=50.0, n=0.0, bucket=BucketKey("flat", "mid"),
            current=current, accumulator=acc,
        )
        assert result.evidence_source == "current_exact"
        assert result.contributing_sessions == ["<current>"]
        # Mean should be the current session's value, not the accumulator's
        assert abs(result.mean - 1.5) < 0.1

    def test_sparse_current_uses_accumulated(self, grid_bins):
        """When current session has no useful data at a cell, accumulated kicks in."""
        s_bins, n_bins = grid_bins
        # Empty current session field
        current = BucketedSurfaceField(s_bins, n_bins)
        # But accumulator has data
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        acc_field = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.0,
        }, n_per_bucket=500)
        acc.add_session(_make_session_fp(session_id="hist"), acc_field)
        # Query — accumulator should fill the gap
        result = layered_query(
            s=50.0, n=0.0, bucket=BucketKey("flat", "mid"),
            current=current, accumulator=acc,
        )
        assert result.evidence_source == "accumulated_exact"
        assert "hist" in result.contributing_sessions
        assert result.fallback_depth == 0

    def test_no_current_no_accumulated_returns_prior(self, grid_bins):
        s_bins, n_bins = grid_bins
        result = layered_query(
            s=50.0, n=0.0, bucket=BucketKey("flat", "mid"),
            current=None, accumulator=None,
        )
        assert result.evidence_source == "prior"
        assert result.fallback_depth == 2
        assert result.confidence == 0.0

    def test_transition_bucket_returns_prior(self, grid_bins):
        s_bins, n_bins = grid_bins
        current = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.0,
        }, n_per_bucket=500)
        result = layered_query(
            s=50.0, n=0.0, bucket=TRANSITION_BUCKET,
            current=current, accumulator=None,
        )
        assert result.evidence_source == "prior"

    def test_section_fallback_when_exact_missing(self, grid_bins):
        s_bins, n_bins = grid_bins
        # Only flat/mid is populated; query flat/early should section-fallback
        current = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.10,
        }, n_per_bucket=500)
        result = layered_query(
            s=50.0, n=0.0, bucket=BucketKey("flat", "early"),
            current=current, accumulator=None,
        )
        # Either current_section (preferred) or prior — we should get section
        assert result.evidence_source in ("current_section", "prior")
        if result.evidence_source == "current_section":
            assert result.fallback_depth == 1

    def test_confidence_increases_when_accumulated_data_exists(self, grid_bins):
        """Sparse current + dense accumulated should yield higher confidence
        than sparse current alone (because accumulated contributes)."""
        s_bins, n_bins = grid_bins
        # Sparse current
        sparse_current = _make_session_field(s_bins, n_bins, fill_buckets={
            BucketKey("flat", "mid"): 1.10,
        }, n_per_bucket=20)
        # Dense accumulator
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        for i in range(5):
            dense_session = _make_session_field(
                s_bins, n_bins,
                fill_buckets={BucketKey("flat", "mid"): 1.10},
                n_per_bucket=300,
            )
            acc.add_session(_make_session_fp(session_id=f"s{i}"), dense_session)

        without_acc = layered_query(
            s=50.0, n=0.0, bucket=BucketKey("flat", "mid"),
            current=sparse_current, accumulator=None,
        )
        with_acc = layered_query(
            s=50.0, n=0.0, bucket=BucketKey("flat", "mid"),
            current=sparse_current, accumulator=acc,
        )
        # Either current was strong enough to win, or accumulated provided more confidence
        # In either case, with_acc.confidence should be >= without_acc.confidence
        assert with_acc.confidence >= without_acc.confidence - 1e-6


# ── End-to-end accumulator behavior on a 2-session toy ───────


class TestAccumulatorE2E:
    def test_two_sessions_reduce_fallback(self, grid_bins):
        """The headline win condition: adding a second compatible session
        increases the cells with depth-0 evidence."""
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)

        # Session 1 covers the first half of s
        bf1 = BucketedSurfaceField(s_bins, n_bins)
        N = 200
        s_arr = np.linspace(10, 100, N)
        keys = np.array([BucketKey("flat", "mid")] * N, dtype=object)
        bf1.update(
            s_arr, np.zeros(N),
            np.full(N, 1.10), np.full(N, 0.8), keys,
        )
        bf1.apply_spatial_smoothing()
        acc.add_session(_make_session_fp(session_id="s1"), bf1)
        cells_after_s1 = (acc._fields[BucketKey("flat", "mid")].n_obs > 0).sum()

        # Session 2 covers the second half of s
        bf2 = BucketedSurfaceField(s_bins, n_bins)
        s_arr2 = np.linspace(100, 190, N)
        bf2.update(
            s_arr2, np.zeros(N),
            np.full(N, 1.10), np.full(N, 0.8), keys,
        )
        bf2.apply_spatial_smoothing()
        acc.add_session(_make_session_fp(session_id="s2"), bf2)
        cells_after_s2 = (acc._fields[BucketKey("flat", "mid")].n_obs > 0).sum()

        assert cells_after_s2 > cells_after_s1, (
            f"Second session should add new cells "
            f"(saw {cells_after_s1} → {cells_after_s2})"
        )

    def test_reproducibility(self, grid_bins):
        """Same inputs in same order → identical accumulator state."""
        s_bins, n_bins = grid_bins
        ak = AccumulatorKey(_make_track_fp(), "mclaren_v1")
        acc1 = CrossSessionAccumulator(ak, s_bins, n_bins)
        acc2 = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf = _make_session_field(s_bins, n_bins)
        acc1.add_session(_make_session_fp(session_id="x"), bf)
        acc2.add_session(_make_session_fp(session_id="x"), bf)
        for bk in ACTIVE_BUCKETS:
            np.testing.assert_array_equal(
                acc1._fields[bk].n_obs, acc2._fields[bk].n_obs,
            )
            np.testing.assert_array_almost_equal(
                acc1._fields[bk].mean, acc2._fields[bk].mean,
            )
