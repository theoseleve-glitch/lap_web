# Theoretical Ghost Overlay — Design Spec

**Date**: 2026-04-03
**Status**: Approved
**Repo**: datalogger (`C:\Users\Admin\Documents\Telemetry\datalogger`)

## Goal

Show the driver what the theoretical optimal is doing at their current track position during a live session. Speed target, throttle/brake target, steering direction, and cumulative time delta — all matched to their real-time position on track.

## Data Flow

```
Pre-session:
  Previous session raw data → sim_optimizer → TheoreticalInputTrace
  → saved as theoretical_ghost.json in session output dir

Live (60Hz):
  TelemetrySample.lap_dist_pct
    → GhostReference.lookup(dist_pct)
    → GhostPoint(speed_kph, throttle_pct, brake_pct, steering_deg)
  Compare to actual sample
    → GhostDelta(speed_delta, throttle_delta, brake_delta, steering_delta)
  Accumulate time delta
    → cumulative_delta_s
  Push to overlay telemetry bindings
```

## File Structure

```
datalogger/src/lap_coach_logger/
  core/
    ghost_reference.py     # Load + lookup theoretical trace (no Qt)
    ghost_tracker.py       # Stateful tracker: sample → delta computation
  overlays/
    builtins.py            # Add theoretical_ghost overlay definition
```

## Module 1: ghost_reference.py

```python
@dataclass(slots=True)
class GhostPoint:
    distance_pct: float
    speed_kph: float
    throttle_pct: float
    brake_pct: float
    steering_deg: float
    cumulative_time_s: float  # theoretical cumulative time at this distance

class GhostReference:
    """Distance-indexed theoretical trace for fast lookup."""

    def __init__(self, trace_path: Path):
        """Load theoretical_ghost.json. Format:
        { "track": str, "car": str, "lap_time_s": float,
          "distance_pct": [...], "speed_kph": [...], "throttle_pct": [...],
          "brake_pct": [...], "steering_deg": [...] }
        """

    @property
    def loaded(self) -> bool: ...

    @property
    def track_name(self) -> str: ...

    @property
    def car_name(self) -> str: ...

    @property
    def theoretical_lap_time_s(self) -> float: ...

    def lookup(self, lap_dist_pct: float) -> GhostPoint | None:
        """Interpolate theoretical values at the given track position.
        Uses np.interp on the distance_pct array for O(1) amortised.
        Returns None if not loaded or dist_pct out of range."""

    @classmethod
    def find_latest(cls, session_output_dir: Path, track_name: str, car_name: str) -> GhostReference | None:
        """Search for most recent theoretical_ghost.json matching track+car."""
```

## Module 2: ghost_tracker.py

```python
@dataclass(slots=True)
class GhostDelta:
    """Per-sample comparison: actual vs theoretical."""
    speed_delta_kph: float       # theoretical - actual (positive = you're slow)
    throttle_delta_pct: float    # theoretical - actual
    brake_delta_pct: float       # theoretical - actual
    steering_delta_deg: float    # theoretical - actual
    cumulative_delta_s: float    # accumulated time loss (positive = losing)
    theoretical_speed_kph: float
    theoretical_throttle_pct: float
    theoretical_brake_pct: float
    theoretical_steering_deg: float

class GhostTracker:
    """Stateful tracker that computes ghost deltas from live samples."""

    def __init__(self, reference: GhostReference):
        self._ref = reference
        self._cumulative_delta_s: float = 0.0
        self._prev_dist_pct: float | None = None
        self._prev_time_s: float | None = None

    def reset(self) -> None:
        """Reset on new lap."""

    def update(self, sample: TelemetrySample) -> GhostDelta | None:
        """Process one sample, return delta or None if reference not loaded.

        Time delta accumulation:
          ds_pct = dist_pct - prev_dist_pct
          dt_actual = session_time - prev_time
          dt_theoretical = ds_pct * track_length / theoretical_speed
          cumulative += dt_actual - dt_theoretical
        """

    @property
    def cumulative_delta_s(self) -> float: ...
```

## Module 3: Overlay definition (builtins.py addition)

New entry in `builtin_overlay_definitions()`:

```python
OverlayDefinition(
    overlay_id="theoretical_ghost",
    renderer_key="theoretical_ghost",
    display_name="Ghost Coach",
    short_description="Theoretical optimal speed, throttle, brake vs your current input.",
    category="coaching",
    tags=("coaching", "ghost", "theoretical", "optimal"),
    search_keywords=("reference", "target", "pace"),
    settings_schema_ref="theoretical_ghost.v1",
    supported_simulators=_ALL_SIMS,
    default_enabled=False,  # user must opt-in
    sort_order=35,
    settings_schema=(
        OverlaySettingField("show_speed", "Show Speed Delta", "bool", "visibility", True),
        OverlaySettingField("show_throttle", "Show Throttle", "bool", "visibility", True),
        OverlaySettingField("show_brake", "Show Brake", "bool", "visibility", True),
        OverlaySettingField("show_steering", "Show Steering", "bool", "visibility", False),
        OverlaySettingField("show_delta_bar", "Show Time Delta", "bool", "visibility", True),
        OverlaySettingField("opacity", "Opacity", "float", "appearance", 0.9,
                            min_value=0.3, max_value=1.0, step=0.05),
    ),
    layout=OverlayLayoutHints(default_width=280, default_height=160,
                               supported_slots=("top_right", "right_center", "bottom_right")),
    entitlement=OverlayEntitlement(tier="premium"),
)
```

## Overlay Visual Layout

Compact panel (~280x160px), dark background, high contrast:

```
┌─────────────────────────────────┐
│  SPD  ▲+12   195 → 183  km/h   │  speed delta + targets
│  ████████░░░░░   THR  92%      │  throttle: solid=actual, line=target
│  ░░░░░░░░░████   BRK   0%      │  brake: solid=actual, line=target
│  ◄══════════►    STR  -42°     │  steering indicator (optional)
│         +0.340s                 │  cumulative delta (green=gaining, red=losing)
└─────────────────────────────────┘
```

Colors:
- Speed delta: green text when gaining (negative), red when losing (positive)
- Throttle bar: solid acid-green actual fill, white ghost marker at theoretical
- Brake bar: solid safety-red actual fill, white ghost marker at theoretical
- Delta: green text when negative (ahead), red when positive (behind)
- Background: #0a0a0a at 90% opacity

## Integration with session_coordinator.py

The `SessionCoordinator` (which orchestrates the recording loop) needs to:

1. On session start: try to load `GhostReference` for the current track+car
2. Create `GhostTracker` if reference found
3. Every sample: call `tracker.update(sample)` and publish the `GhostDelta` to overlay bindings
4. On lap boundary: call `tracker.reset()`

## Ghost JSON Format

```json
{
  "version": 1,
  "track_name": "Red Bull Ring",
  "car_name": "Porsche 911 GT3 R (992)",
  "theoretical_lap_time_s": 87.102,
  "generated_at": "2026-04-03T...",
  "n_points": 500,
  "distance_pct": [0.0, 0.002, 0.004, ...],
  "speed_kph": [80.0, 82.5, 85.1, ...],
  "throttle_pct": [1.0, 1.0, 1.0, ...],
  "brake_pct": [0.0, 0.0, 0.0, ...],
  "steering_deg": [-12.5, -11.8, -10.2, ...]
}
```

~500 points is enough for sub-1% distance resolution. File size ~50KB.

## Export from sim_optimizer

Add to the runner script / pipeline: after computing `TheoreticalInputTrace`, export as `theoretical_ghost.json` in the session directory. This is the bridge between the webapp optimizer and the logger ghost overlay.

## Testing

- `test_ghost_reference.py`: load JSON, lookup at various distances, verify interpolation
- `test_ghost_tracker.py`: feed synthetic samples, verify delta accumulation, verify lap reset
- Integration: verify overlay definition loads in registry
