#!/usr/bin/env python3
"""bless_gt.py — validate + admit a hand-traced ground-truth geojson into the corpus.

Usage:
    python scripts/bless_gt.py <geojson> --canonical-id <id> \
        [--alias <name> ...] [--force]

Pipeline (Task 8 extraction: the validate -> copy -> register-alias core
now lives in ``telemetry_tool.onboarding.bless_service.install_gt_geojson``
so this CLI and the web bless path (``bless_service.bless_geometry``,
always ``force=False``) share ONE code path for the actual corpus install.
This module's ``bless_gt()`` is now a thin wrapper with an unchanged
signature/behavior):
    1. Run track_surface.gt_validate.validate_gt_geojson() on the input file.
       Any message refuses the bless unless --force is passed — EXCEPT a
       missing/empty `reviewed_by`, which is refused unconditionally (only
       a human-reviewed export may ship; --force cannot override this one).
    2. Refuse a canonical_id that already exists in the alias registry,
       unless --force (in which case the existing entry is merged into,
       not replaced — its other keys such as country/notes are preserved).
    3. Copy the file to data/ground_truth/gt_<id>.geojson (shutil.copy2).
    4. Register `<id>` itself plus any --alias values into
       telemetry_tool/track_surface/track_aliases.json, preserving the
       registry's existing key order/style (no sort_keys, no reordering of
       pre-existing entries).
    5. Print (never execute) the SQL to point tracks.canonical_id at this
       id on prod, plus a reminder that data/ground_truth/ is baked into
       the backend Docker image and needs a redeploy to take effect.

--gt-dir / --aliases-file let callers (tests, dry runs) point this at
temporary locations instead of the real corpus/registry; both default to
the real repo paths when omitted.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TELEMETRY_PKG = _REPO_ROOT / "telemetry_tool"
for _p in (_REPO_ROOT, _TELEMETRY_PKG):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from onboarding.bless_service import InstallError as BlessError  # noqa: E402
from onboarding.bless_service import install_gt_geojson  # noqa: E402

DEFAULT_GT_DIR = _REPO_ROOT / "data" / "ground_truth"
DEFAULT_ALIASES_FILE = _TELEMETRY_PKG / "track_surface" / "track_aliases.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="bless_gt.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("geojson", type=Path, help="Path to the reviewed gt_*.geojson export")
    p.add_argument("--canonical-id", required=True, dest="canonical_id",
                   help="Canonical track id to bless this file as (e.g. kct, ok)")
    p.add_argument("--alias", action="append", default=[], dest="aliases",
                   help="Additional alias to register (repeatable)")
    p.add_argument("--force", action="store_true",
                   help="Bless despite validator warnings or a duplicate canonical_id. "
                        "Does NOT override a missing reviewed_by — that refusal is absolute.")
    p.add_argument("--gt-dir", type=Path, default=None, dest="gt_dir",
                   help=f"Override ground_truth output dir (default: {DEFAULT_GT_DIR})")
    p.add_argument("--aliases-file", type=Path, default=None, dest="aliases_file",
                   help=f"Override track_aliases.json path (default: {DEFAULT_ALIASES_FILE})")
    return p.parse_args(argv)


def bless_gt(
    geojson_path: Path,
    canonical_id: str,
    *,
    aliases: list[str] | None = None,
    force: bool = False,
    gt_dir: Path | None = None,
    aliases_file: Path | None = None,
) -> Path:
    """Validate + admit ``geojson_path`` into the gt corpus as ``canonical_id``.

    Returns the destination path on success. Raises :class:`BlessError` on
    any refusal — this function never calls ``sys.exit``; that's ``main``'s
    job, so tests can assert on the exception directly.

    Thin wrapper (Task 8 extraction): the actual validate -> copy ->
    register-alias logic now lives in
    ``telemetry_tool.onboarding.bless_service.install_gt_geojson`` so this
    CLI and the web bless path (``bless_service.bless_geometry``, which
    hard-wires ``force=False``) share exactly one code path for the corpus
    install. This function's signature and behavior are unchanged by the
    extraction.
    """
    gt_dir = Path(gt_dir) if gt_dir is not None else DEFAULT_GT_DIR
    aliases_file = Path(aliases_file) if aliases_file is not None else DEFAULT_ALIASES_FILE
    return install_gt_geojson(
        Path(geojson_path), canonical_id,
        aliases=aliases, force=force,
        gt_dir=gt_dir, aliases_file=aliases_file,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        dest = bless_gt(
            args.geojson, args.canonical_id,
            aliases=args.aliases, force=args.force,
            gt_dir=args.gt_dir, aliases_file=args.aliases_file,
        )
    except BlessError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Refusing to bless: {exc}", file=sys.stderr)
        return 1

    all_aliases = [args.canonical_id, *args.aliases]
    print(f"Blessed {args.geojson} -> {dest}")
    print(f"Registered aliases for '{args.canonical_id}': {all_aliases}")
    print()
    print("-- Run manually against prod once this change is deployed (NOT executed here) --")
    print(f"UPDATE tracks SET canonical_id = '{args.canonical_id}' "
          f"WHERE track_id = '<TRACK_UUID>';  -- substitute the real track_id")
    print()
    print("Reminder: data/ground_truth/ is baked into the backend Docker image "
          "(Dockerfile COPYs it at build time) — redeploy the backend after merging "
          "this change for the new/updated gt file to take effect in prod.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
