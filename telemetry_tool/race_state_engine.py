"""
race_state_engine.py
--------------------
Event-driven race state engine with fuel cascade and ballast decomposition.

Manages the full lifecycle of stint fuel and ballast calculations,
propagating changes downstream whenever a parameter is toggled.

Public API
~~~~~~~~~~
``FuelModel``
    Linear fuel consumption model (dataclass).
``StintState``
    Enriched stint with fuel, ballast, and constraint state (dataclass).
``RaceStateEngine``
    Event-driven engine: fuel cascade, ballast decomposition, real-time interpolation.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FuelModel
# ---------------------------------------------------------------------------

@dataclass
class FuelModel:
    """Linear fuel consumption model.

    Attributes
    ----------
    full_tank_kg : float
        Fuel mass only (full_tank_kg config - empty_kart_kg config).
    fuel_autonomy_s : int
        How long a full tank lasts in seconds.
    quali_fuel_used_kg : float
        Fuel consumed during qualifying (0.0 if refueled after quali).
    """

    full_tank_kg: float
    fuel_autonomy_s: int
    quali_fuel_used_kg: float = 0.0

    @property
    def burn_rate_kgs(self) -> float:
        """Fuel burn rate in kg/s.  Returns 0.0 if autonomy is zero."""
        if self.fuel_autonomy_s <= 0:
            return 0.0
        return self.full_tank_kg / self.fuel_autonomy_s

    @property
    def fuel_after_quali_kg(self) -> float:
        """Fuel remaining after qualifying, clamped to >= 0."""
        return max(0.0, self.full_tank_kg - self.quali_fuel_used_kg)

    @classmethod
    def from_config(cls, config: dict) -> FuelModel:
        """Build from a race_configs dict row."""
        empty = config.get("empty_kart_kg") or 0.0
        full_tank = config.get("full_tank_kg") or 0.0
        fuel_capacity = max(0.0, full_tank - empty)
        autonomy = config.get("fuel_autonomy_s") or 0
        quali_used = 0.0
        if autonomy > 0 and not config.get("refuel_after_quali", 0):
            quali_dur = config.get("qualifying_duration_s") or 0
            burn_rate = fuel_capacity / autonomy if autonomy else 0
            quali_used = burn_rate * quali_dur
        return cls(
            full_tank_kg=fuel_capacity,
            fuel_autonomy_s=autonomy,
            quali_fuel_used_kg=quali_used,
        )


# ---------------------------------------------------------------------------
# StintState
# ---------------------------------------------------------------------------

@dataclass
class StintState:
    """Enriched stint with fuel, ballast, and constraint state.

    Core fields mirror the ``race_stints`` DB table; computed fields
    (fuel, ballast, violations) are populated by :class:`RaceStateEngine`.
    """

    stint_order: int
    driver_id: int
    driver_name: str
    planned_duration_s: int
    planned_start_s: int
    planned_end_s: int
    fuel_at_start_kg: float = 0.0
    fuel_at_end_kg: float = 0.0
    refueled_before: bool = True
    ballast_kg: float = 0.0
    ballast_base_kg: float = 0.0
    ballast_fuel_offset_kg: float = 0.0
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    actual_start_s: int | None = None
    actual_end_s: int | None = None
    actual_duration_s: int | None = None
    status: str = "planned"
    notes: str = ""


# ---------------------------------------------------------------------------
# RaceStateEngine
# ---------------------------------------------------------------------------

class RaceStateEngine:
    """Event-driven engine with fuel cascade and ballast decomposition.

    Parameters
    ----------
    config : dict
        Race configuration (from ``race_configs`` row or optimizer input).
    drivers : dict or list
        Drivers keyed by ID (``dict[int, dict]``) **or** a list of driver
        dicts each containing an ``"id"`` key.  Lists are normalised to
        ``dict[int, dict]`` on init.
    raw_stints : list[dict]
        Stint dicts from the optimizer or DB (``stint_order``, ``driver_id``,
        ``planned_duration_s``, ``planned_start_s``, ``planned_end_s``).
    pit_stops : list[dict] | None
        Pit stop dicts (``after_stint``, ``refuel``, ``driver_change``).
    """

    def __init__(
        self,
        config: dict[str, Any],
        drivers: dict[int, dict[str, Any]] | list[dict[str, Any]],
        raw_stints: list[dict[str, Any]],
        pit_stops: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config = config

        # Normalise drivers: accept list-of-dicts or dict-keyed-by-id
        if isinstance(drivers, list):
            self.drivers: dict[int, dict[str, Any]] = {d["id"]: d for d in drivers}
        else:
            self.drivers = drivers

        self.fuel_model = FuelModel.from_config(config)

        # Convert raw stint dicts into StintState objects
        self.stints: list[StintState] = []
        for s in raw_stints:
            driver_id = s["driver_id"]
            driver = self._get_driver(driver_id)
            self.stints.append(
                StintState(
                    stint_order=s["stint_order"],
                    driver_id=driver_id,
                    driver_name=driver.get("driver_name", "Unknown"),
                    planned_duration_s=s["planned_duration_s"],
                    planned_start_s=s["planned_start_s"],
                    planned_end_s=s["planned_end_s"],
                )
            )

        # Build refuel and pit type maps from pit_stops
        self._pit_stops = pit_stops or []
        self._refuel_map: dict[int, bool] = self._init_refuel_map()
        # _pit_type_map: stint_order -> pit type string ("full" / "quick")
        # Keyed by the stint that *follows* the pit stop (i.e. after_stint + 1).
        self._pit_type_map: dict[int, str] = {}
        for ps in self._pit_stops:
            after = ps["after_stint"]
            self._pit_type_map[after + 1] = ps.get("pit_type", "full")

        # Run initial cascade from stint 1
        if self.stints:
            self._cascade_from(1)

    # -- internal helpers ---------------------------------------------------

    def _init_refuel_map(self) -> dict[int, bool]:
        """Build refuel map from pit stops.

        Stint 1 is always True (starts with fuel).
        If ``refueling_allowed=0`` in config, all subsequent stints are False.
        Otherwise, refuel status comes from pit stop data.
        """
        refuel_map: dict[int, bool] = {}
        refueling_allowed = bool(self.config.get("refueling_allowed", 1))

        # Stint 1 always has fuel (either full or post-quali)
        refuel_map[1] = True

        # Build from pit_stops
        pit_refuel: dict[int, bool] = {}
        for ps in self._pit_stops:
            after = ps["after_stint"]
            # The stint *after* the pit stop gets refueled
            pit_refuel[after + 1] = bool(ps.get("refuel", True))

        for s in self.stints:
            order = s.stint_order
            if order == 1:
                continue
            if not refueling_allowed:
                refuel_map[order] = False
            elif order in pit_refuel:
                refuel_map[order] = pit_refuel[order]
            else:
                # Default: refueled if there's a pit stop before this stint
                refuel_map[order] = True

        return refuel_map

    def _get_stint(self, stint_order: int) -> StintState | None:
        """Get a stint by its order number."""
        for s in self.stints:
            if s.stint_order == stint_order:
                return s
        return None

    def _get_driver(self, driver_id: int) -> dict[str, Any]:
        """Get driver dict by ID."""
        return self.drivers.get(driver_id, {"id": driver_id, "driver_name": "Unknown", "weight_kg": 0.0})

    def _cascade_from(self, from_order: int) -> None:
        """Propagate fuel and ballast from *from_order* onward.

        Iterates stints in order, calling ``_calc_fuel_state``,
        ``_calc_ballast``, and ``_validate_constraints`` on each.
        """
        for s in self.stints:
            if s.stint_order < from_order:
                continue
            s.refueled_before = self._refuel_map.get(s.stint_order, True)
            self._calc_fuel_state(s)
            self._calc_ballast(s)
            self._validate_constraints(s)

    def _calc_fuel_state(self, stint: StintState) -> None:
        """Calculate fuel_at_start and fuel_at_end for a stint.

        ``fuel_at_end_kg`` is *not* clamped to zero so that constraint
        validation can detect fuel exhaustion (negative values).
        """
        fm = self.fuel_model

        if stint.stint_order == 1:
            # First stint: starts with fuel_after_quali
            stint.fuel_at_start_kg = fm.fuel_after_quali_kg
        elif stint.refueled_before:
            # Refueled: starts with a full tank
            stint.fuel_at_start_kg = fm.full_tank_kg
        else:
            # Not refueled: carry from previous stint
            prev = self._get_stint(stint.stint_order - 1)
            if prev is not None:
                stint.fuel_at_start_kg = prev.fuel_at_end_kg
            else:
                stint.fuel_at_start_kg = 0.0

        # Fuel consumed during the stint (may go negative)
        consumed = fm.burn_rate_kgs * stint.planned_duration_s
        stint.fuel_at_end_kg = stint.fuel_at_start_kg - consumed

    def _calc_ballast(self, stint: StintState) -> None:
        """Calculate ballast decomposition for a stint.

        ballast_base = max(0, min_kart - empty - fuel_capacity - driver_weight)
        ballast_fuel_offset = max(0, fuel_capacity - fuel_at_start)
        ballast_kg = base + offset (rounded to 2 decimals)
        """
        min_kart = self.config.get("min_total_kart_kg") or 0.0
        empty = self.config.get("empty_kart_kg") or 0.0
        fuel_capacity = self.fuel_model.full_tank_kg
        driver = self._get_driver(stint.driver_id)
        driver_weight = driver.get("weight_kg") or 0.0

        stint.ballast_base_kg = max(0.0, min_kart - empty - fuel_capacity - driver_weight)
        stint.ballast_fuel_offset_kg = max(0.0, fuel_capacity - stint.fuel_at_start_kg)
        stint.ballast_kg = round(stint.ballast_base_kg + stint.ballast_fuel_offset_kg, 2)

    def _validate_constraints(self, stint: StintState) -> None:
        """Validate constraints for a stint and populate violations/warnings.

        Checks:
        1. Fuel exhaustion (fuel_at_end < 0)
        2. Minimum rest time between same-driver stints
        3. Mandatory driver change at every pit stop
        4. Cumulative driving time per driver
        """
        stint.violations = []
        stint.warnings = []
        driver = self._get_driver(stint.driver_id)

        # 1. Fuel exhaustion: if fuel_at_end < 0
        if stint.fuel_at_end_kg < 0:
            if self.fuel_model.burn_rate_kgs > 0:
                runout_s = stint.planned_start_s + (
                    stint.fuel_at_start_kg / self.fuel_model.burn_rate_kgs
                )
                stint.violations.append(
                    f"Fuel runs out at {int(runout_s)}s into race"
                )
            else:
                stint.violations.append("Fuel exhausted but no burn rate configured")

        # 2. Min rest time: find the LAST previous stint by this driver, check gap
        min_rest = driver.get("min_rest_s")
        if min_rest and stint.stint_order > 1:
            prev_by_driver = None
            for prev in self.stints:
                if prev.stint_order >= stint.stint_order:
                    break
                if prev.driver_id == stint.driver_id:
                    prev_by_driver = prev
            if prev_by_driver:
                gap = stint.planned_start_s - prev_by_driver.planned_end_s
                if gap < min_rest:
                    stint.violations.append(
                        f"{driver['driver_name']}: {gap}s rest, needs {min_rest}s"
                    )

        # 3. Mandatory driver change: consecutive stints must have different drivers
        if self.config.get("mandatory_driver_change") and stint.stint_order > 1:
            prev = self._get_stint(stint.stint_order - 1)
            if prev and prev.driver_id == stint.driver_id:
                stint.violations.append(
                    "Mandatory driver change required at every pit stop"
                )

        # 4. Cumulative time: sum all this driver's stints up to current
        max_cum = driver.get("max_cumulative_s")
        if max_cum:
            cumulative = sum(
                s.planned_duration_s
                for s in self.stints
                if s.driver_id == stint.driver_id and s.stint_order <= stint.stint_order
            )
            if cumulative > max_cum:
                stint.violations.append(
                    f"{driver['driver_name']}: {cumulative}s exceeds max {max_cum}s"
                )
            elif cumulative > max_cum * 0.9:
                stint.warnings.append(
                    f"{driver['driver_name']}: {cumulative}s is 90%+ of max {max_cum}s"
                )

    # -- public mutation API ------------------------------------------------

    def set_driver(self, stint_order: int, driver_id: int) -> None:
        """Change the driver for a stint and re-cascade."""
        stint = self._get_stint(stint_order)
        if not stint:
            return
        driver = self._get_driver(driver_id)
        if not driver:
            return
        stint.driver_id = driver_id
        stint.driver_name = driver.get("driver_name", "")
        self._cascade_from(stint_order)

    def set_duration(self, stint_order: int, duration_s: int) -> None:
        """Change the planned duration for a stint and rebuild the timeline."""
        stint = self._get_stint(stint_order)
        if not stint:
            return
        stint.planned_duration_s = duration_s
        stint.planned_end_s = stint.planned_start_s + duration_s
        # Rebuild timeline for subsequent stints
        pit_time = self.config.get("min_pit_stop_s") or 60
        for s in self.stints:
            if s.stint_order <= stint_order:
                continue
            prev = self._get_stint(s.stint_order - 1)
            if prev:
                quick = self._pit_type_map.get(s.stint_order) == "quick"
                stop_dur = (
                    (self.config.get("quick_pit_stop_s") or pit_time) if quick else pit_time
                )
                s.planned_start_s = prev.planned_end_s + stop_dur
                s.planned_end_s = s.planned_start_s + s.planned_duration_s
        self._cascade_from(stint_order)

    def set_pit_type(self, stint_order: int, pit_type: str) -> None:
        """Set pit type for the pit stop before *stint_order*.

        A "quick" pit disables refuelling for that stop.
        """
        if stint_order <= 1:
            return
        self._pit_type_map[stint_order] = pit_type
        if pit_type == "quick":
            self._refuel_map[stint_order] = False
        self._cascade_from(stint_order)

    def toggle_fuel(self, stint_order: int) -> None:
        """Toggle refuel status for a stint and cascade downstream."""
        if stint_order == 1:
            # Stint 1 cannot be toggled -- it always starts with fuel
            return
        current = self._refuel_map.get(stint_order, True)
        self._refuel_map[stint_order] = not current
        self._cascade_from(stint_order)

    # -- real-time interpolation API ----------------------------------------

    def current_fuel_kg(self, elapsed_s: float) -> float:
        """Interpolate current fuel level at a given elapsed time.

        Parameters
        ----------
        elapsed_s : float
            Seconds elapsed from race start.

        Returns
        -------
        float
            Estimated fuel in kg at the given time (clamped >= 0).
        """
        stint = self._find_active_stint(elapsed_s)
        if stint is None:
            return 0.0
        time_into_stint = elapsed_s - stint.planned_start_s
        time_into_stint = max(0.0, min(time_into_stint, stint.planned_duration_s))
        consumed = self.fuel_model.burn_rate_kgs * time_into_stint
        return max(0.0, stint.fuel_at_start_kg - consumed)

    def current_ballast(self, elapsed_s: float) -> dict[str, Any]:
        """Real-time ballast decomposition at a given elapsed time.

        Parameters
        ----------
        elapsed_s : float
            Seconds elapsed from race start.

        Returns
        -------
        dict
            Keys: ballast_base_kg, ballast_fuel_offset_kg, ballast_kg,
            driver_name, fuel_kg.
        """
        stint = self._find_active_stint(elapsed_s)
        if stint is None:
            return {
                "ballast_base_kg": 0.0,
                "ballast_fuel_offset_kg": 0.0,
                "ballast_kg": 0.0,
                "driver_name": "N/A",
                "fuel_kg": 0.0,
            }

        fuel_now = self.current_fuel_kg(elapsed_s)
        fuel_capacity = self.fuel_model.full_tank_kg
        driver = self._get_driver(stint.driver_id)
        driver_weight = driver.get("weight_kg") or 0.0

        min_kart = self.config.get("min_total_kart_kg") or 0.0
        empty = self.config.get("empty_kart_kg") or 0.0

        base = max(0.0, min_kart - empty - fuel_capacity - driver_weight)
        fuel_offset = max(0.0, fuel_capacity - fuel_now)
        total = round(base + fuel_offset, 2)

        return {
            "ballast_base_kg": base,
            "ballast_fuel_offset_kg": fuel_offset,
            "ballast_kg": total,
            "driver_name": stint.driver_name,
            "fuel_kg": fuel_now,
        }

    def _find_active_stint(self, elapsed_s: float) -> StintState | None:
        """Find the active stint at a given elapsed time.

        Checks for ``status="active"`` first, then falls back to time range.
        """
        # Check for an explicitly active stint
        for s in self.stints:
            if s.status == "active":
                return s

        # Fall back to planned time range
        for s in self.stints:
            if s.planned_start_s <= elapsed_s <= s.planned_end_s:
                return s

        # If past all stints, return the last one
        if self.stints and elapsed_s >= self.stints[-1].planned_end_s:
            return self.stints[-1]

        return None

    # -- persistence API ----------------------------------------------------

    def save(self, conn, race_id: int) -> None:
        """Persist stints and pit stops to the database.

        Deletes existing rows for *race_id* then inserts current state.

        Parameters
        ----------
        conn : sqlite3.Connection
            Database connection (with row_factory if desired).
        race_id : int
            The race_configs.race_id to save under.
        """
        cur = conn.cursor()

        # Clear existing data for this race
        cur.execute("DELETE FROM race_pit_stops WHERE race_id = ?", (race_id,))
        cur.execute("DELETE FROM race_stints WHERE race_id = ?", (race_id,))

        # Insert stints
        for s in self.stints:
            cur.execute(
                "INSERT INTO race_stints "
                "(race_id, stint_order, driver_id, planned_start_s, planned_end_s, "
                " planned_duration_s, actual_start_s, actual_end_s, actual_duration_s, "
                " fuel_at_start, fuel_at_end, ballast_kg, ballast_base_kg, "
                " ballast_fuel_offset_kg, fuel_burn_rate_kgs, notes, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    race_id,
                    s.stint_order,
                    s.driver_id,
                    s.planned_start_s,
                    s.planned_end_s,
                    s.planned_duration_s,
                    s.actual_start_s,
                    s.actual_end_s,
                    s.actual_duration_s,
                    round(s.fuel_at_start_kg, 4),
                    round(s.fuel_at_end_kg, 4),
                    round(s.ballast_kg, 2),
                    round(s.ballast_base_kg, 2),
                    round(s.ballast_fuel_offset_kg, 2),
                    round(self.fuel_model.burn_rate_kgs, 6),
                    s.notes,
                    s.status,
                ),
            )

        # Insert pit stops (reconstruct from _pit_type_map / _refuel_map)
        pit_time = self.config.get("min_pit_stop_s") or 60
        for s in self.stints:
            if s.stint_order == 1:
                continue
            prev = self._get_stint(s.stint_order - 1)
            if not prev:
                continue
            pit_type = self._pit_type_map.get(s.stint_order, "full")
            quick = pit_type == "quick"
            stop_dur = (self.config.get("quick_pit_stop_s") or pit_time) if quick else pit_time
            refueled = self._refuel_map.get(s.stint_order, True)
            driver_change = int(prev.driver_id != s.driver_id)

            # Find the stint_id just inserted for the preceding stint
            row = cur.execute(
                "SELECT stint_id FROM race_stints "
                "WHERE race_id = ? AND stint_order = ?",
                (race_id, prev.stint_order),
            ).fetchone()
            stint_id = row[0] if row else None

            cur.execute(
                "INSERT INTO race_pit_stops "
                "(race_id, stint_id, planned_at_s, duration_s, driver_change, "
                " refueled, pit_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    race_id,
                    stint_id,
                    prev.planned_end_s,
                    stop_dur,
                    driver_change,
                    int(refueled),
                    pit_type,
                ),
            )

        conn.commit()

    @classmethod
    def load(cls, conn, race_id: int) -> RaceStateEngine:
        """Load engine state from the database.

        Parameters
        ----------
        conn : sqlite3.Connection
            Database connection (should have ``row_factory = sqlite3.Row``).
        race_id : int
            The race to load.

        Returns
        -------
        RaceStateEngine
            A fully-initialised engine with fuel cascade applied.
        """
        # Load config
        config_row = conn.execute(
            "SELECT * FROM race_configs WHERE race_id = ?", (race_id,)
        ).fetchone()
        if config_row is None:
            raise ValueError(f"race_id {race_id} not found in race_configs")
        config = dict(config_row)

        # Load drivers
        driver_rows = conn.execute(
            "SELECT * FROM race_drivers WHERE race_id = ? ORDER BY driver_order",
            (race_id,),
        ).fetchall()
        drivers = [dict(r) for r in driver_rows]

        # Load stints with driver_name via JOIN
        stint_rows = conn.execute(
            "SELECT rs.*, rd.driver_name "
            "FROM race_stints rs "
            "JOIN race_drivers rd ON rs.driver_id = rd.id "
            "WHERE rs.race_id = ? ORDER BY rs.stint_order",
            (race_id,),
        ).fetchall()
        raw_stints = []
        for row in stint_rows:
            rd = dict(row)
            raw_stints.append({
                "stint_order": rd["stint_order"],
                "driver_id": rd["driver_id"],
                "driver_name": rd["driver_name"],
                "planned_start_s": rd["planned_start_s"],
                "planned_end_s": rd["planned_end_s"],
                "planned_duration_s": rd["planned_duration_s"],
            })

        # Load pit stops and infer after_stint from ordering
        pit_rows = conn.execute(
            "SELECT * FROM race_pit_stops WHERE race_id = ? ORDER BY planned_at_s",
            (race_id,),
        ).fetchall()
        pit_stops = []
        for i, row in enumerate(pit_rows):
            rd = dict(row)
            pit_stops.append({
                "after_stint": i + 1,  # pit stop after stint i+1
                "at_s": rd.get("planned_at_s"),
                "duration_s": rd.get("duration_s"),
                "refuel": bool(rd.get("refueled", 0)),
                "driver_change": bool(rd.get("driver_change", 0)),
                "pit_type": rd.get("pit_type", "full"),
            })

        return cls(config, drivers, raw_stints, pit_stops)

    def snapshot(self) -> dict[str, Any]:
        """Return a complete in-memory snapshot of engine state.

        Returns
        -------
        dict
            Keys: ``fuel_model``, ``stints``, ``refuel_map``, ``pit_type_map``.
        """
        fm = self.fuel_model
        stint_dicts = []
        for s in self.stints:
            d = asdict(s)
            # Round numeric fields for readability
            for key in (
                "fuel_at_start_kg", "fuel_at_end_kg",
                "ballast_kg", "ballast_base_kg", "ballast_fuel_offset_kg",
            ):
                if d.get(key) is not None:
                    d[key] = round(d[key], 4)
            stint_dicts.append(d)

        return {
            "fuel_model": {
                "full_tank_kg": fm.full_tank_kg,
                "fuel_autonomy_s": fm.fuel_autonomy_s,
                "quali_fuel_used_kg": fm.quali_fuel_used_kg,
                "burn_rate_kgs": round(fm.burn_rate_kgs, 6),
            },
            "stints": stint_dicts,
            "refuel_map": dict(self._refuel_map),
            "pit_type_map": dict(self._pit_type_map),
        }

    def stint_plan_export(self, race_name: str) -> dict[str, Any]:
        """Export a lightweight stint plan for sharing.

        Parameters
        ----------
        race_name : str
            Human-readable race name for the export header.

        Returns
        -------
        dict
            Portable plan with format version, stints, and pit stops.
        """
        stints_out = []
        for s in self.stints:
            stints_out.append({
                "stint_order": s.stint_order,
                "driver_name": s.driver_name,
                "planned_duration_s": s.planned_duration_s,
                "refueled_before": s.refueled_before,
                "ballast_kg": round(s.ballast_kg, 2),
                "ballast_base_kg": round(s.ballast_base_kg, 2),
                "ballast_fuel_offset_kg": round(s.ballast_fuel_offset_kg, 2),
            })

        pit_stops_out = []
        pit_time = self.config.get("min_pit_stop_s") or 60
        for s in self.stints:
            if s.stint_order == 1:
                continue
            prev = self._get_stint(s.stint_order - 1)
            if not prev:
                continue
            pit_type = self._pit_type_map.get(s.stint_order, "full")
            quick = pit_type == "quick"
            stop_dur = (self.config.get("quick_pit_stop_s") or pit_time) if quick else pit_time
            refueled = self._refuel_map.get(s.stint_order, True)
            driver_change = prev.driver_id != s.driver_id
            pit_stops_out.append({
                "after_stint": prev.stint_order,
                "duration_s": stop_dur,
                "driver_change": driver_change,
                "refueled": refueled,
                "pit_type": pit_type,
            })

        return {
            "format": "stint-plan-v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "race_name": race_name,
            "stints": stints_out,
            "pit_stops": pit_stops_out,
        }
