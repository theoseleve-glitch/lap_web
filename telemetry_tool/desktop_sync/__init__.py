"""Desktop-to-cloud session sync for Lap's simracing analysis.

Modules:
  - config          : user preferences (auto_upload toggle)
  - bundle_builder  : capture folder → ManifestV2 zip
  - queue           : SQLite sync queue (pending/uploaded/failed)
  - worker          : background upload thread with retry
"""
