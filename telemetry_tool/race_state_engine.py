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
from dataclasses import dataclass, field
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
    drivers : dict
        Drivers keyed by ID.  Each value has at least ``id``, ``driver_name``,
        ``weight_kg``.
    raw_stints : list[dict]
        Stint dicts from the optimizer or DB (``stint_order``, ``driver_id``,
        ``planned_duration_s``, ``planned_start_s``, ``planned_end_s``).
    pit_stops : list[dict] | None
        Pit stop dicts (``after_stint``, ``refuel``, ``driver_change``).
    """

    def __init__(
        self,
        config: dict[str, Any],
        drivers: dict[int, dict[str, Any]],
        raw_stints: list[dict[str, Any]],
        pit_stops: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config = config
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
        self._pit_type_map: dict[int, dict] = {}
        for ps in self._pit_stops:
            self._pit_type_map[ps["after_stint"]] = ps

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
        """Calculate fuel_at_start and fuel_at_end for a stint."""
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

        # Fuel consumed during the stint
        consumed = fm.burn_rate_kgs * stint.planned_duration_s
        stint.fuel_at_end_kg = max(0.0, stint.fuel_at_start_kg - consumed)

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
        """Placeholder for constraint validation (Task 4).

        Clears violations/warnings for now.
        """
        stint.violations = []
        stint.warnings = []

    # -- public API ---------------------------------------------------------

    def toggle_fuel(self, stint_order: int) -> None:
        """Toggle refuel status for a stint and cascade downstream."""
        if stint_order == 1:
            # Stint 1 cannot be toggled — it always starts with fuel
            return
        current = self._refuel_map.get(stint_order, True)
        self._refuel_map[stint_order] = not current
        self._cascade_from(stint_order)

    def current_fuel_kg(self, elapsed_s: float) -> float:
        """Interpolate current fuel level at a given elapsed time.

        Parameters
        ----------
        elapsed_s : float
            Seconds elapsed from race start.

        Returns
        -------
        float
            Estimated fuel in kg at the given time.
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
