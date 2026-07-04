# Runbook — Racing-Line Release (optimizer honesty layer)

**Scope:** shipping a change that affects computed racing lines — the 2D/quasi-3D
solver, the grip field, track geometry, or the honesty layer itself. These
changes alter what a driver sees on track, so the bar is: **never ship a line
that isn't honest about what it is.**

**Owner:** optimizer / Race Brief. **Audience:** whoever deploys `telemetry_tool`.

---

## The one hard gate

A solver/geometry/honesty change may deploy to prod **only if**:

```bash
cd telemetry_tool
python -m scripts.validate_racing_lines --require-lines
echo "exit=$?"   # MUST be 0
```

- Exit **0** → every persisted `status='ok'` line passes the physics
  self-consistency validator. Safe to deploy.
- Exit **2** → at least one line is RED (or, with `--require-lines`, there are
  no lines to check). **Do not deploy.** Investigate the RED lines first
  (`--json` prints per-line detail).

The gate is fail-safe: a validator that errors counts a line as RED, never as a
silent pass. There is no `--force`.

## Migration order (080)

Migration `080_racing_line_honesty` adds `geometry_source`, `tier`, and
`provenance` to `track_racing_lines` (all nullable, backward-compatible). Apply
it **before** deploying the worker that writes those columns:

```bash
cd telemetry_tool
alembic upgrade 080_racing_line_honesty   # chains off 079_track_geometry_audit
```

Old rows keep NULL tiers until re-solved; consumers treat NULL/unknown as
not-drawable (see contract below), so a partial rollout is safe. 080 is a
prod-affecting migration — deploy is gated on explicit diff confirmation.

## The tier rendering contract (for consumers)

Every consumer that renders a line (Race Brief Lanes 3-4, the webapp, any
overlay) MUST branch on `tier` and call the guard — never render a raw line:

```python
from track_surface.honesty import is_drawable_as_line

if is_drawable_as_line(line["tier"]):
    draw_racing_line(line["points"])      # ONLY optimal_line reaches here
else:
    # speed_profile_only -> a speed/colour overlay on the track, NEVER a line
    # refused / None / unknown -> render nothing; show why from provenance
    ...
```

Tier vocabulary is **closed at three values** — enforced by
`tests/test_racing_line_tier_contract.py`:

| tier | meaning | may draw as a line? |
|---|---|---|
| `optimal_line` | GT-verified geometry + grip≥gold + validation green + solved | **yes** |
| `speed_profile_only` | solved, but geometry derived/absent, or grip<gold, or validation red | no — speed overlay only |
| `refused` | solve failed / infeasible / gates failed | no — render nothing |

`provenance` (JSONB) carries the audit: `laps_used`, grip confidence summary,
geometry gates version, solver name/version, the validation report, and (on a
degraded/refused line) `tier_reason` from the honesty taxonomy.

## Pre-deploy checklist

1. `alembic upgrade 080_racing_line_honesty` applied to the target DB.
2. `python -m scripts.validate_racing_lines --require-lines` → exit 0.
3. (Advisory) `python -m scripts.report_vs_real_laps` — review any
   "predicted slower than real" smells. Non-gating: a smell does not block, but
   a large/systematic one warrants a look before shipping.
4. Deploy diff confirmed (solver/migration changes are prod-affecting).

## Rollback

The columns are additive and nullable — rolling the worker back to a version
that ignores them is safe; the honesty columns simply stop updating. Do **not**
downgrade migration 080 with live data referencing the columns.
