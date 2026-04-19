"""Tests for the ops module — registry / manifest / accumulator tooling."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from track_surface.condition_bucketing import (
    BucketKey,
    BucketedSurfaceField,
)
from track_surface.cross_session_accumulator import (
    AccumulatorKey,
    CrossSessionAccumulator,
    SessionFingerprint,
    TrackFingerprint,
)
from track_surface.validation import ops


# ── Vehicle profile ops ─────────────────────────────────────


class TestAddVehicleProfile:
    def test_add_to_empty_registry(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        result = ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v1", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.5, tire_d1_long=2.4,
            roll_compliance=0.003,
        )
        assert result.ok
        assert "x_v1" in result.message
        assert reg_path.is_file()
        loaded = json.loads(reg_path.read_text())
        assert loaded["version"] == 1
        assert loaded["profiles"][0]["profile_id"] == "x_v1"
        assert loaded["profiles"][0]["active"] is True

    def test_add_duplicate_id_rejected(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v1", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.5, tire_d1_long=2.4, roll_compliance=0.003,
        )
        result = ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v1", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.5, tire_d1_long=2.4, roll_compliance=0.003,
        )
        assert not result.ok
        assert "already exists" in result.message

    def test_add_second_version_for_same_vehicle_deactivates_first(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v1", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.5, tire_d1_long=2.4, roll_compliance=0.003,
        )
        ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v2", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.7, tire_d1_long=2.6, roll_compliance=0.004,
        )
        loaded = json.loads(reg_path.read_text())
        active = [p for p in loaded["profiles"] if p["active"]]
        assert len(active) == 1
        assert active[0]["profile_id"] == "x_v2"

    def test_no_activate_keeps_inactive(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        result = ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v1", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.5, tire_d1_long=2.4, roll_compliance=0.003,
            activate=False,
        )
        assert result.ok
        loaded = json.loads(reg_path.read_text())
        assert loaded["profiles"][0]["active"] is False


class TestDeprecateProfile:
    def test_deprecate_existing(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v1", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.5, tire_d1_long=2.4, roll_compliance=0.003,
        )
        result = ops.deprecate_profile(
            registry_path=reg_path, profile_id="x_v1", reason="superseded by x_v2",
        )
        assert result.ok
        loaded = json.loads(reg_path.read_text())
        prof = loaded["profiles"][0]
        assert prof["deprecated"] is True
        assert prof["active"] is False
        assert "DEPRECATED" in prof["notes"]

    def test_deprecate_unknown(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        # Create empty registry first
        ops.add_vehicle_profile(
            registry_path=reg_path,
            profile_id="x_v1", vehicle_key="x", vehicle_class="GT4",
            tire_d1_lat=2.5, tire_d1_long=2.4, roll_compliance=0.003,
        )
        result = ops.deprecate_profile(registry_path=reg_path, profile_id="nope")
        assert not result.ok
        assert "not found" in result.message


class TestActivateProfile:
    def test_activate_deactivates_siblings(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        ops.add_vehicle_profile(
            registry_path=reg_path, profile_id="x_v1", vehicle_key="x",
            vehicle_class="GT4", tire_d1_lat=2.5, tire_d1_long=2.4,
            roll_compliance=0.003, activate=True,
        )
        ops.add_vehicle_profile(
            registry_path=reg_path, profile_id="x_v2", vehicle_key="x",
            vehicle_class="GT4", tire_d1_lat=2.7, tire_d1_long=2.6,
            roll_compliance=0.004, activate=False,
        )
        # v1 active, v2 inactive (because we passed activate=False)
        # Activate v2: should deactivate v1
        result = ops.activate_profile(registry_path=reg_path, profile_id="x_v2")
        assert result.ok
        loaded = json.loads(reg_path.read_text())
        active_ids = [p["profile_id"] for p in loaded["profiles"] if p["active"]]
        assert active_ids == ["x_v2"]

    def test_activate_unknown(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        ops.add_vehicle_profile(
            registry_path=reg_path, profile_id="x_v1", vehicle_key="x",
            vehicle_class="GT4", tire_d1_lat=2.5, tire_d1_long=2.4,
            roll_compliance=0.003,
        )
        result = ops.activate_profile(registry_path=reg_path, profile_id="nope")
        assert not result.ok

    def test_activate_deprecated_rejected(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        ops.add_vehicle_profile(
            registry_path=reg_path, profile_id="x_v1", vehicle_key="x",
            vehicle_class="GT4", tire_d1_lat=2.5, tire_d1_long=2.4,
            roll_compliance=0.003,
        )
        ops.deprecate_profile(registry_path=reg_path, profile_id="x_v1")
        result = ops.activate_profile(registry_path=reg_path, profile_id="x_v1")
        assert not result.ok
        assert "deprecated" in result.message


class TestListProfiles:
    def test_empty(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        # Create empty registry
        result = ops.list_profiles(registry_path=reg_path)
        assert result.ok
        assert result.details["profiles"] == []

    def test_lists_all_profiles(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        ops.add_vehicle_profile(
            registry_path=reg_path, profile_id="x_v1", vehicle_key="x",
            vehicle_class="GT4", tire_d1_lat=2.5, tire_d1_long=2.4,
            roll_compliance=0.003,
        )
        ops.add_vehicle_profile(
            registry_path=reg_path, profile_id="y_v1", vehicle_key="y",
            vehicle_class="TouringCar", tire_d1_lat=2.7, tire_d1_long=2.6,
            roll_compliance=0.004,
        )
        result = ops.list_profiles(registry_path=reg_path)
        assert result.ok
        ids = [p["profile_id"] for p in result.details["profiles"]]
        assert ids == ["x_v1", "y_v1"]


# ── Manifest ops ────────────────────────────────────────────


def _good_manifest(tmp_path) -> Path:
    p = tmp_path / "m.json"
    p.write_text(json.dumps({
        "version": 1,
        "datasets": [{
            "id": "existing",
            "ibt_path": str(tmp_path / "stub.ibt"),
            "group": "A_banked",
            "track": {"name": "X", "layout": "L", "regime": "flat"},
            "vehicle": {
                "name": "X", "class": "GT4", "drive_layout": "RWD",
                "mass_kg": 1000, "wheelbase_m": 2.5,
                "track_front_m": 1.5, "track_rear_m": 1.5,
                "weight_dist_front": 0.5, "aero_cla": 1.0, "cg_height_m": 0.3,
                "brake_bias_front": 0.5, "steer_ratio": 14.0,
                "camber_front_deg": -3.0, "camber_rear_deg": -2.0,
            },
        }],
    }))
    return p


class TestAddDataset:
    def test_add_valid_entry(self, tmp_path):
        manifest = _good_manifest(tmp_path)
        new_entry = {
            "id": "new_one",
            "ibt_path": str(tmp_path / "new.ibt"),
            "group": "B_flat_low_speed",
            "track": {"name": "Y", "layout": "L", "regime": "flat"},
            "vehicle": {
                "name": "Y", "class": "GT4", "drive_layout": "RWD",
                "mass_kg": 1100, "wheelbase_m": 2.6,
                "track_front_m": 1.5, "track_rear_m": 1.5,
                "weight_dist_front": 0.5, "aero_cla": 1.0, "cg_height_m": 0.3,
                "brake_bias_front": 0.5, "steer_ratio": 14.0,
                "camber_front_deg": -3.0, "camber_rear_deg": -2.0,
            },
        }
        result = ops.add_dataset_to_manifest(manifest_path=manifest, entry=new_entry)
        assert result.ok
        loaded = json.loads(manifest.read_text())
        assert len(loaded["datasets"]) == 2
        assert loaded["datasets"][1]["id"] == "new_one"

    def test_add_duplicate_id(self, tmp_path):
        manifest = _good_manifest(tmp_path)
        loaded = json.loads(manifest.read_text())
        dup = dict(loaded["datasets"][0])
        result = ops.add_dataset_to_manifest(manifest_path=manifest, entry=dup)
        assert not result.ok
        assert "already in manifest" in result.message

    def test_add_invalid_entry_rejected(self, tmp_path):
        manifest = _good_manifest(tmp_path)
        bad = {"id": "bad"}  # missing many required fields
        result = ops.add_dataset_to_manifest(manifest_path=manifest, entry=bad)
        assert not result.ok
        assert "rejected" in result.message


class TestValidateManifest:
    def test_validates_good_manifest(self, tmp_path):
        manifest = _good_manifest(tmp_path)
        result = ops.validate_manifest(manifest_path=manifest)
        assert result.ok
        assert "1 datasets" in result.message
        assert result.details["datasets"][0]["id"] == "existing"

    def test_invalid_manifest_reported(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"version": 1, "datasets": [{"id": "x"}]}))
        result = ops.validate_manifest(manifest_path=bad)
        assert not result.ok
        assert "invalid" in result.message.lower()


# ── Accumulator inspection ──────────────────────────────────


class TestInspectAccumulator:
    def test_empty_dir(self, tmp_path):
        result = ops.inspect_accumulator(accumulator_dir=tmp_path)
        assert result.ok
        assert result.details["accumulators"] == []

    def test_missing_dir(self, tmp_path):
        result = ops.inspect_accumulator(accumulator_dir=tmp_path / "nope")
        assert not result.ok

    def test_summarizes_real_accumulator(self, tmp_path):
        # Create a real accumulator + add a session
        s_bins = np.arange(0, 110, 10.0)
        n_bins = np.arange(-5, 6, 1.0)
        ak = AccumulatorKey(
            track_fingerprint=TrackFingerprint(name="X", layout="L", length_m=100.0),
            calibration_profile_id="prof_v1",
        )
        acc = CrossSessionAccumulator(ak, s_bins, n_bins)
        bf = BucketedSurfaceField(s_bins, n_bins)
        keys = np.array([BucketKey("flat", "mid")] * 100, dtype=object)
        bf.update(
            np.linspace(10, 90, 100), np.zeros(100),
            np.full(100, 1.10), np.full(100, 0.8), keys,
        )
        acc.add_session(SessionFingerprint(
            session_id="my_session",
            track_fingerprint=ak.track_fingerprint,
            calibration_profile_id="prof_v1",
            n_valid_samples=10000,
        ), bf)
        acc.save(tmp_path)
        result = ops.inspect_accumulator(accumulator_dir=tmp_path)
        assert result.ok
        accs = result.details["accumulators"]
        assert len(accs) == 1
        assert accs[0]["n_contributions"] == 1
        assert "my_session" in accs[0]["contributing_sessions"]
        assert accs[0]["calibration_profile_id"] == "prof_v1"


# ── Smoke pick ──────────────────────────────────────────────


class TestSmokePick:
    def test_no_files_present(self, tmp_path):
        manifest = _good_manifest(tmp_path)
        result = ops.smoke_test_manifest(manifest_path=manifest)
        # Stub .ibt path doesn't exist → no candidates
        assert not result.ok
        assert "No manifest datasets" in result.message

    def test_picks_smallest_file(self, tmp_path):
        # Create two .ibt files of different sizes, add both to a manifest
        big = tmp_path / "big.ibt"
        big.write_bytes(b"x" * 1000)
        small = tmp_path / "small.ibt"
        small.write_bytes(b"x" * 10)
        manifest = tmp_path / "m.json"
        veh = {
            "name": "X", "class": "GT4", "drive_layout": "RWD",
            "mass_kg": 1000, "wheelbase_m": 2.5,
            "track_front_m": 1.5, "track_rear_m": 1.5,
            "weight_dist_front": 0.5, "aero_cla": 1.0, "cg_height_m": 0.3,
            "brake_bias_front": 0.5, "steer_ratio": 14.0,
            "camber_front_deg": -3.0, "camber_rear_deg": -2.0,
        }
        track = {"name": "X", "layout": "L", "regime": "flat"}
        manifest.write_text(json.dumps({
            "version": 1,
            "datasets": [
                {"id": "big_one", "ibt_path": str(big), "group": "A_banked",
                 "track": track, "vehicle": veh},
                {"id": "small_one", "ibt_path": str(small), "group": "A_banked",
                 "track": track, "vehicle": veh},
            ],
        }))
        result = ops.smoke_test_manifest(manifest_path=manifest, max_datasets=1)
        assert result.ok
        assert result.details["chosen_ids"] == ["small_one"]

    def test_only_filter_applied(self, tmp_path):
        big = tmp_path / "big.ibt"
        big.write_bytes(b"x" * 1000)
        small = tmp_path / "small.ibt"
        small.write_bytes(b"x" * 10)
        manifest = tmp_path / "m.json"
        veh = {
            "name": "X", "class": "GT4", "drive_layout": "RWD",
            "mass_kg": 1000, "wheelbase_m": 2.5,
            "track_front_m": 1.5, "track_rear_m": 1.5,
            "weight_dist_front": 0.5, "aero_cla": 1.0, "cg_height_m": 0.3,
            "brake_bias_front": 0.5, "steer_ratio": 14.0,
            "camber_front_deg": -3.0, "camber_rear_deg": -2.0,
        }
        track = {"name": "X", "layout": "L", "regime": "flat"}
        manifest.write_text(json.dumps({
            "version": 1,
            "datasets": [
                {"id": "big_one", "ibt_path": str(big), "group": "A_banked",
                 "track": track, "vehicle": veh},
                {"id": "small_one", "ibt_path": str(small), "group": "A_banked",
                 "track": track, "vehicle": veh},
            ],
        }))
        # Only big_one allowed → must pick it even though smaller exists
        result = ops.smoke_test_manifest(
            manifest_path=manifest, only=["big_one"], max_datasets=1,
        )
        assert result.ok
        assert result.details["chosen_ids"] == ["big_one"]
