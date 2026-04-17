"""
track_surface/gold_lab.py
-------------------------
Gold Lab zone intelligence — shared s-bin classifier.

The Gold Lab UI, the build pipeline's JSON assembler, and the tests all
need to agree on what "this bin" looks like. This module is the single
source of truth for that classification.

For each s-bin we answer:
  • Is the bank estimate confident?
  • Is the bin plausible or suspicious per the plausibility audit?
  • Did the Beta correction actually fire on this bin?

The output is one of:

    high_conf_plausible_applied      — correction fired in a plausible zone
    high_conf_suspicious_applied     — correction fired in a suspicious zone (flag)
    high_conf_neither_applied        — correction fired, neither plausible nor suspicious
    low_conf_raw_passthrough         — correction skipped, neutral geometry
    low_conf_suspicious              — correction skipped, known-suspicious geometry
    neutral_unclassified             — nothing to say

A human-readable *explanation* string is also produced so the UI tooltip
and the compare drawer render the same text without reinventing the
reasoning.

Invariant: this module reads data; it never mutates it. All functions are
pure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


# ── Canonical zone class labels (single source of truth) ────────

ZONE_CLASSES: tuple[str, ...] = (
    'high_conf_plausible_applied',
    'high_conf_suspicious_applied',
    'high_conf_neither_applied',
    'low_conf_raw_passthrough',
    'low_conf_suspicious',
    'neutral_unclassified',
)

# Pretty labels for the viewer
ZONE_PRETTY: dict[str, str] = {
    'high_conf_plausible_applied':  'Applied (plausible)',
    'high_conf_suspicious_applied': 'Applied (suspicious)',
    'high_conf_neither_applied':    'Applied (neutral)',
    'low_conf_raw_passthrough':     'Raw pass-through',
    'low_conf_suspicious':          'Skipped (suspicious)',
    'neutral_unclassified':         'Neutral',
}


@dataclass
class PlausibilityFlags:
    """Subset of the bank_field_plausibility CSV columns that matter for
    zone classification. All values are ``0 / 1`` integers in the CSV.
    ``is_plausible`` is derived from the audit's tight-and-confident rule.
    """
    flag_conf_spread: int = 0
    flag_gradient: int = 0
    flag_banked_straight: int = 0
    is_plausible: bool = False

    @classmethod
    def from_csv_row(cls, row: dict) -> 'PlausibilityFlags':
        """Construct from one CSV row of the plausibility audit output."""
        def _i(k: str) -> int:
            try:
                return int(float(row.get(k, 0) or 0))
            except (TypeError, ValueError):
                return 0
        def _f(k: str) -> float:
            try:
                return float(row.get(k, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        # Plausible per the audit's heuristic:
        #   bank_confidence ≥ 0.60 AND bank_std_deg ≤ 2.0 AND |bank| ≥ 1.0
        is_plausible = (
            _f('bank_confidence') >= 0.60
            and _f('bank_std_deg') <= 2.0
            and abs(_f('bank_mean_deg')) >= 1.0
        )
        return cls(
            flag_conf_spread=_i('flag_conf_spread'),
            flag_gradient=_i('flag_gradient'),
            flag_banked_straight=_i('flag_banked_straight'),
            is_plausible=is_plausible,
        )


def _is_suspicious(flags: PlausibilityFlags) -> bool:
    return bool(
        flags.flag_conf_spread
        or flags.flag_gradient
        or flags.flag_banked_straight
    )


def classify_s_bin_zone(
    *,
    bank_confidence: float,
    applied: bool,
    plausibility_flags: Optional[PlausibilityFlags] = None,
    conf_threshold: float = 0.60,
) -> str:
    """Classify a single s-bin.

    Parameters
    ----------
    bank_confidence : 0..1
    applied         : did the correction fire on this bin?
    plausibility_flags : optional audit flags. If None, we assume neutral.
    conf_threshold  : gate above which confidence is considered "high".
                      Defaults to 0.60 (shared with the shadow path).

    Returns
    -------
    One of ``ZONE_CLASSES``.
    """
    pflags = plausibility_flags or PlausibilityFlags()
    suspicious = _is_suspicious(pflags)
    plausible = bool(pflags.is_plausible)
    high_conf = bank_confidence >= conf_threshold

    if applied:
        # Correction fired
        if plausible:
            return 'high_conf_plausible_applied'
        if suspicious:
            return 'high_conf_suspicious_applied'
        return 'high_conf_neither_applied'
    # Correction skipped
    if suspicious:
        return 'low_conf_suspicious'
    if not high_conf:
        return 'low_conf_raw_passthrough'
    return 'neutral_unclassified'


def explain_s_bin(
    *,
    bank_confidence: float,
    applied: bool,
    plausibility_flags: Optional[PlausibilityFlags] = None,
    conf_threshold: float = 0.60,
) -> str:
    """Human-readable explanation string for the tooltip / compare drawer."""
    pflags = plausibility_flags or PlausibilityFlags()
    suspicious = _is_suspicious(pflags)
    plausible = bool(pflags.is_plausible)

    if applied:
        if plausible:
            return 'correction applied: bank field confidence above threshold, plausible zone'
        if suspicious:
            return 'correction applied: bank field confidence above threshold, but suspicious geometry'
        return 'correction applied: bank field confidence above threshold'
    # Skipped
    if suspicious and bank_confidence < conf_threshold:
        return 'correction skipped: confidence below threshold, suspicious zone'
    if suspicious:
        return 'correction skipped: suspicious geometry zone'
    if bank_confidence < conf_threshold:
        return f'correction skipped: confidence {bank_confidence:.2f} below threshold {conf_threshold:.2f}'
    return 'correction skipped: outside applied mask'


def classify_zones_bulk(
    bank_confidence_arr: Iterable[float],
    applied_arr: Iterable[bool],
    plausibility_rows: Optional[Iterable[Optional[PlausibilityFlags]]] = None,
    conf_threshold: float = 0.60,
) -> list[str]:
    """Vectorised wrapper. Returns a list of class strings, one per bin.

    ``plausibility_rows`` may be None (no audit data); in that case every
    bin is classified without plausibility signal, which keeps the Gold
    Lab degrading gracefully.
    """
    bank_confidence_arr = list(bank_confidence_arr)
    applied_arr = list(applied_arr)
    n = len(bank_confidence_arr)
    if plausibility_rows is None:
        plaus_list = [None] * n
    else:
        plaus_list = list(plausibility_rows)
        if len(plaus_list) != n:
            raise ValueError(
                f'plausibility_rows length {len(plaus_list)} != '
                f'bank_confidence length {n}'
            )
    out: list[str] = []
    for i in range(n):
        out.append(classify_s_bin_zone(
            bank_confidence=float(bank_confidence_arr[i]),
            applied=bool(applied_arr[i]),
            plausibility_flags=plaus_list[i],
            conf_threshold=conf_threshold,
        ))
    return out


def zone_counts(classes: Iterable[str]) -> dict[str, int]:
    """Aggregate class counts. Classes not seen default to 0."""
    counts = {k: 0 for k in ZONE_CLASSES}
    for c in classes:
        if c in counts:
            counts[c] += 1
    return counts
