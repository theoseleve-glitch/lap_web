"""CauseTaxonomy — loads and validates causes.json, provides lookup methods."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, field_validator


class CauseDefinition(BaseModel):
    symptom: str
    diagnosis: str
    root_cause: str
    severity_thresholds: dict[str, float]
    unit: str

    @field_validator("root_cause")
    @classmethod
    def validate_root_cause(cls, v: str) -> str:
        valid = {"technique", "confidence", "line", "balance",
                 "aggression", "fitness", "management", "awareness", "fear"}
        if v not in valid:
            raise ValueError(f"Invalid root_cause: {v}")
        return v

    @field_validator("severity_thresholds")
    @classmethod
    def validate_thresholds(cls, v: dict) -> dict:
        for key in ("mild", "moderate", "severe"):
            if key not in v:
                raise ValueError(f"Missing severity threshold: {key}")
        return v


class CauseTaxonomy:
    def __init__(self, path: str | None = None):
        if path is None:
            path = str(Path(__file__).parent / "causes.json")
        with open(path, "r") as f:
            raw = json.load(f)
        self.categories: dict[str, dict[str, dict]] = {}
        self._cause_to_category: dict[str, str] = {}
        for cat_name, cat_data in raw.get("categories", {}).items():
            causes = {}
            for cause_id, cause_data in cat_data.get("causes", {}).items():
                # Validate via Pydantic — raises ValueError if invalid
                CauseDefinition(**cause_data)
                causes[cause_id] = cause_data
                self._cause_to_category[cause_id] = cat_name
            self.categories[cat_name] = causes

    def get_cause(self, cause_id: str) -> dict | None:
        return next(
            (causes[cause_id] for causes in self.categories.values()
             if cause_id in causes), None)

    def get_category(self, cause_id: str) -> str | None:
        return self._cause_to_category.get(cause_id)

    def get_severity(self, cause_id: str, delta: float) -> str:
        cause = self.get_cause(cause_id)
        if cause is None:
            return "moderate"
        thresholds = cause["severity_thresholds"]
        if abs(delta) >= thresholds["severe"]:
            return "severe"
        if abs(delta) >= thresholds["moderate"]:
            return "moderate"
        return "mild"
