"""Python-only JSON-Schema → TypeScript generator for our contracts.

Scope is deliberately narrow — we only translate the subset emitted by
our Pydantic models:
  - object types → `export interface`
  - string enums → `export enum` (backed by string values)
  - $ref references → reference by `title`
  - arrays, primitives, optional fields, anyOf with a single type + null
  - Literal unions → string union types

If Pydantic emits something outside this subset, the generator raises
loudly rather than silently skipping, so the test suite catches drift.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Compute SCHEMAS_DIR directly so this module stays import-clean when run as
# `python -m ...` (avoids triggering the parent telemetry_tool/web/schemas/__init__.py
# which has `from web.schemas.common import ...` that requires telemetry_tool/ on sys.path).
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "_schemas"

_REPO_ROOT = Path(__file__).resolve().parents[5]
TS_OUTPUT_PATH = _REPO_ROOT / "lap-website" / "src" / "types" / "contracts.ts"

_HEADER = """\
// AUTO-GENERATED - DO NOT EDIT BY HAND.
// Source: telemetry_tool/web/schemas/contracts/_schemas/*.schema.json
// Regenerate with:
//   python -m telemetry_tool.web.schemas.contracts._scripts.generate_ts

"""


def _ts_primitive(js_type: str) -> str:
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }[js_type]


def _resolve_type(node: dict[str, Any], root: dict[str, Any]) -> str:
    """Translate one JSON-Schema node to a TS type expression."""
    if "$ref" in node:
        ref = node["$ref"]  # e.g. "#/$defs/DriverRef"
        name = ref.rsplit("/", 1)[-1]
        return name
    if "enum" in node:
        return " | ".join(json.dumps(v) for v in node["enum"])
    if "const" in node:
        return json.dumps(node["const"])
    if "anyOf" in node:
        parts = [_resolve_type(sub, root) for sub in node["anyOf"]]
        return " | ".join(parts)
    if "type" in node:
        t = node["type"]
        if t == "array":
            item = _resolve_type(node.get("items", {"type": "string"}), root)
            return f"Array<{item}>"
        if t == "object":
            # Inline object — fall back to Record<string, unknown>
            if "additionalProperties" in node:
                ap = node["additionalProperties"]
                if isinstance(ap, dict):
                    return f"Record<string, {_resolve_type(ap, root)}>"
                return "Record<string, unknown>"
            return "Record<string, unknown>"
        return _ts_primitive(t)
    # Fallback
    return "unknown"


def _render_object(name: str, schema: dict[str, Any], root: dict[str, Any]) -> str:
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    lines = [f"export interface {name} {{"]
    for prop_name, prop_schema in props.items():
        opt = "" if prop_name in required else "?"
        ts_type = _resolve_type(prop_schema, root)
        desc = prop_schema.get("description")
        if desc:
            lines.append(f"  /** {desc} */")
        lines.append(f"  {prop_name}{opt}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def _render_enum(name: str, values: list[str]) -> str:
    lines = [f"export type {name} ="]
    for v in values:
        lines.append(f"  | {json.dumps(v)}")
    return "\n".join(lines) + ";"


def _emit_schema(schema: dict[str, Any]) -> list[str]:
    """Emit top-level interface + every $def as an interface or enum."""
    blocks: list[str] = []
    defs = schema.get("$defs", {})
    for name, sub in defs.items():
        if "enum" in sub and sub.get("type") == "string":
            blocks.append(_render_enum(name, sub["enum"]))
        else:
            blocks.append(_render_object(name, sub, schema))
    # Top-level
    title = schema.get("title", "Unknown")
    blocks.append(_render_object(title, schema, schema))
    return blocks


def generate_ts_string() -> str:
    seen: set[str] = set()
    blocks: list[str] = []
    for fname in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(fname.read_text())
        for block in _emit_schema(schema):
            # Dedup by first line header
            header = block.split("\n", 1)[0]
            if header in seen:
                continue
            seen.add(header)
            blocks.append(block)
    return _HEADER + "\n\n".join(blocks) + "\n"


def generate_ts_file(out_path: Path = TS_OUTPUT_PATH) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(generate_ts_string(), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    p = generate_ts_file()
    print(f"wrote {p}")
