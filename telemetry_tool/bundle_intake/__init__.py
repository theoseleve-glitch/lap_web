"""Bundle intake bounded context.

Accepts canonical logger bundles (schema_version=2), validates them as a
product contract, persists the raw archive immutably, extracts normalized
metadata, assesses analysis readiness, and hands off to track_surface_app.

Sub-modules:
  - domain         : enums + dataclasses
  - errors         : typed exceptions mapped to ErrorCode
  - manifest_schema: Pydantic ManifestV2 model
  - validator      : archive + schema + inner-checksum rules
  - storage        : content-addressed raw storage (immutable on disk)
  - readiness      : AnalysisReadinessEvaluator
  - persistence    : BundleRepository
  - service        : IntakeService — glues the above
"""
