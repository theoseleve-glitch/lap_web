from __future__ import annotations

import json
from dataclasses import replace

from kart_envelope.config import default_config
from kart_envelope.inference.policy import select_driver_policy


def test_policy_selects_mpc_imitation_when_available(tmp_path):
    cfg = replace(
        default_config(),
        policy_enable_virtual_driver=True,
        policy_enable_advanced_driver=False,
        policy_enable_mpc_imitation=True,
        policy_mpc_confidence_threshold=0.70,
    )
    bundle = tmp_path / "bundle_v2"
    bundle.mkdir(parents=True, exist_ok=True)
    with open(bundle / "mpc_imitation_policy.json", "w", encoding="utf-8") as fh:
        json.dump({
            "available": True,
            "rows": 120,
            "coverage": 0.82,
            "confidence": 0.88,
            "notes": "test",
        }, fh)

    sel = select_driver_policy(config=cfg, quality_score=0.84, bundle_dir=bundle)
    assert sel.selected_policy == "advanced_mpc_imitation"
    assert sel.mpc_available is True
    assert sel.confidence >= 0.70


def test_policy_falls_back_to_virtual_without_mpc(tmp_path):
    cfg = replace(
        default_config(),
        policy_enable_virtual_driver=True,
        policy_enable_advanced_driver=False,
        policy_enable_mpc_imitation=True,
        policy_mpc_confidence_threshold=0.90,
    )
    bundle = tmp_path / "bundle_v2"
    bundle.mkdir(parents=True, exist_ok=True)
    sel = select_driver_policy(config=cfg, quality_score=0.55, bundle_dir=bundle)
    assert sel.selected_policy == "virtual_reference_policy"
    assert sel.mpc_available is False

