"""
SQLite schema definitions for the telemetry analysis platform.

All CREATE TABLE statements live here as constants so that
``migrate.ensure_schema`` can apply them idempotently.
"""

# Current schema version -- bump when adding/altering tables.
SCHEMA_VERSION = 32

# ------------------------------------------------------------------
# Phase 1 tables
# ------------------------------------------------------------------

_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version      INTEGER PRIMARY KEY,
    applied_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    description  TEXT
);
"""

_TRACKS_TABLE = """
CREATE TABLE IF NOT EXISTS tracks (
    track_id      TEXT PRIMARY KEY,
    track_name    TEXT NOT NULL,
    lap_length_m  REAL NOT NULL,
    bbox_lat_min  REAL,
    bbox_lat_max  REAL,
    bbox_lon_min  REAL,
    bbox_lon_max  REAL,
    start_lat     REAL,
    start_lon     REAL,
    sample_count  INTEGER,
    lap_count     INTEGER,
    has_joker              INTEGER NOT NULL DEFAULT 0,
    joker_distance_delta_m REAL,
    joker_time_delta_s     REAL,
    dry_ref_session_id  TEXT REFERENCES sessions(session_id),
    wet_ref_session_id  TEXT REFERENCES sessions(session_id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_DRIVERS_TABLE = """
CREATE TABLE IF NOT EXISTS drivers (
    driver_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_name  TEXT    NOT NULL UNIQUE,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    notes        TEXT
);
"""

_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    csv_filename      TEXT NOT NULL,
    driver_id         INTEGER NOT NULL REFERENCES drivers(driver_id),
    track_id          TEXT    REFERENCES tracks(track_id),
    session_type      TEXT    NOT NULL DEFAULT 'practice',
    track_state       TEXT    NOT NULL DEFAULT 'dry',
    session_date      TEXT    NOT NULL,
    n_laps            INTEGER,
    best_lap_time_s   REAL,
    mean_lap_time_s   REAL,
    total_score       REAL,
    grade             TEXT,
    weather_json      TEXT,
    notes             TEXT,
    html_report_path  TEXT,
    simulation_method TEXT,
    joker_lap_number  INTEGER,
    analysis_json     TEXT,
    display_name      TEXT,
    source_filename   TEXT,
    source_path       TEXT,
    kart_id           INTEGER REFERENCES karts(kart_id),
    data_tier         INTEGER NOT NULL DEFAULT 1,
    available_channels TEXT,
    source_format     TEXT    DEFAULT 'racechrono',
    source_metadata   TEXT,
    pipeline_version_hash TEXT DEFAULT 'unknown',
    model_version     TEXT    DEFAULT 'none',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_LAPS_TABLE = """
CREATE TABLE IF NOT EXISTS laps (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT    NOT NULL REFERENCES sessions(session_id),
    lap_number        INTEGER NOT NULL,
    lap_time_s        REAL,
    speed_mean_mps    REAL,
    speed_max_mps     REAL,
    braking_max_mps2  REAL,
    accel_max_mps2    REAL,
    line_length_m     REAL,
    is_valid          INTEGER NOT NULL DEFAULT 1,
    is_best           INTEGER NOT NULL DEFAULT 0,
    phase_id          INTEGER,
    invalid_reason    TEXT,
    is_joker          INTEGER NOT NULL DEFAULT 0,
    UNIQUE(session_id, lap_number)
);
"""

_GPS_TRACES_TABLE = """
CREATE TABLE IF NOT EXISTS gps_traces (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT    NOT NULL REFERENCES sessions(session_id),
    lap_number         INTEGER NOT NULL,
    latitudes_json     TEXT    NOT NULL,
    longitudes_json    TEXT    NOT NULL,
    distances_json     TEXT    NOT NULL,
    speeds_json        TEXT    NOT NULL,
    accel_lat_json     TEXT,
    accel_long_json    TEXT,
    throttle_json      TEXT,
    brake_json         TEXT,
    steering_json      TEXT,
    rpm_json           TEXT,
    gear_json          TEXT,
    tire_temp_json     TEXT,
    tire_pressure_json TEXT,
    brake_temp_json    TEXT,
    wheel_slip_json    TEXT,
    fuel_json          TEXT,
    UNIQUE(session_id, lap_number)
);
"""

_SCORE_DETAILS_TABLE = """
CREATE TABLE IF NOT EXISTS score_details (
    session_id         TEXT PRIMARY KEY REFERENCES sessions(session_id),
    pace_score         REAL,
    pace_max           REAL,
    consistency_score  REAL,
    consistency_max    REAL,
    execution_score    REAL,
    execution_max      REAL,
    robustness_score   REAL,
    robustness_max     REAL,
    strengths_json     TEXT,
    weaknesses_json    TEXT,
    adaptation_score   REAL
);
"""

_CONDITION_PHASES_TABLE = """
CREATE TABLE IF NOT EXISTS condition_phases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL REFERENCES sessions(session_id),
    phase_id       INTEGER NOT NULL,
    lap_start      INTEGER NOT NULL,
    lap_end        INTEGER NOT NULL,
    label          TEXT,
    confidence     REAL,
    median_pace_s  REAL,
    UNIQUE(session_id, phase_id)
);
"""

# Ordered list: tables must be created in dependency order.
PHASE_1_TABLES: list[tuple[str, str]] = [
    ("schema_version",   _SCHEMA_VERSION_TABLE),
    ("tracks",           _TRACKS_TABLE),
    ("drivers",          _DRIVERS_TABLE),
    ("sessions",         _SESSIONS_TABLE),
    ("laps",             _LAPS_TABLE),
    ("gps_traces",       _GPS_TRACES_TABLE),
    ("score_details",    _SCORE_DETAILS_TABLE),
    ("condition_phases", _CONDITION_PHASES_TABLE),
]

# ------------------------------------------------------------------
# Phase 2 tables
# ------------------------------------------------------------------

_WEEKENDS_TABLE = """
CREATE TABLE IF NOT EXISTS weekends (
    weekend_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT,
    track_id     TEXT    REFERENCES tracks(track_id),
    start_date   TEXT,
    end_date     TEXT,
    notes        TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_WEEKEND_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS weekend_sessions (
    weekend_id     INTEGER NOT NULL REFERENCES weekends(weekend_id),
    session_id     TEXT    NOT NULL REFERENCES sessions(session_id),
    session_order  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (weekend_id, session_id)
);
"""

_TRACK_RECORDS_TABLE = """
CREATE TABLE IF NOT EXISTS track_records (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id       TEXT    NOT NULL REFERENCES tracks(track_id),
    record_time_s  REAL    NOT NULL,
    record_holder  TEXT,
    record_date    TEXT,
    vehicle_class  TEXT,
    source         TEXT,
    UNIQUE(track_id, vehicle_class)
);
"""

_CONDITION_MARKERS_TABLE = """
CREATE TABLE IF NOT EXISTS condition_markers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL REFERENCES sessions(session_id),
    lap_number   INTEGER NOT NULL,
    new_state    TEXT    NOT NULL,
    notes        TEXT,
    UNIQUE(session_id, lap_number)
);
"""

PHASE_2_TABLES: list[tuple[str, str]] = [
    ("weekends",          _WEEKENDS_TABLE),
    ("weekend_sessions",  _WEEKEND_SESSIONS_TABLE),
    ("track_records",     _TRACK_RECORDS_TABLE),
    ("condition_markers", _CONDITION_MARKERS_TABLE),
]

# ------------------------------------------------------------------
# Phase 3 tables
# ------------------------------------------------------------------

_DRIVER_PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS driver_profiles (
    driver_id          INTEGER PRIMARY KEY REFERENCES drivers(driver_id),
    weight_kg          REAL,
    kart_class         TEXT,
    experience_level   TEXT,
    goals              TEXT,
    preferred_tracks   TEXT,
    custom_notes       TEXT,
    email              TEXT,
    phone              TEXT,
    id_code            TEXT,
    pace_delta_mean_s  REAL,
    consistency_rating REAL,
    aggression_index   REAL,
    smoothness_index   REAL,
    improvement_trend  TEXT,
    total_sessions     INTEGER NOT NULL DEFAULT 0,
    total_laps         INTEGER NOT NULL DEFAULT 0,
    best_ever_time_s   REAL,
    best_ever_track_id TEXT,
    wet_skill_proxy    REAL,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_DRIVER_PROGRESSION_TABLE = """
CREATE TABLE IF NOT EXISTS driver_progression (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id         INTEGER NOT NULL REFERENCES drivers(driver_id),
    session_id        TEXT    NOT NULL REFERENCES sessions(session_id),
    session_date      TEXT,
    track_id          TEXT,
    pace_delta_s      REAL,
    consistency_cv_pct REAL,
    aggression_index  REAL,
    smoothness_index  REAL,
    total_score       REAL,
    n_laps            INTEGER,
    UNIQUE(driver_id, session_id)
);
"""

_DRIVING_STYLE_FEATURES_TABLE = """
CREATE TABLE IF NOT EXISTS driving_style_features (
    id                             INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id                      INTEGER NOT NULL REFERENCES drivers(driver_id),
    session_id                     TEXT    NOT NULL REFERENCES sessions(session_id),
    trail_braking_depth            REAL,
    brake_point_consistency        REAL,
    brake_pressure_buildup_rate    REAL,
    apex_speed_ratio               REAL,
    turn_in_aggressiveness         REAL,
    throttle_onset_delay_m         REAL,
    exit_acceleration_efficiency   REAL,
    line_variation_index           REAL,
    early_vs_late_stint_pace       REAL,
    smoothness_composite           REAL,
    style_label                    TEXT,
    style_confidence               REAL,
    strengths_json                 TEXT,
    weaknesses_json                TEXT,
    computed_at                    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(driver_id, session_id)
);
"""

PHASE_3_TABLES: list[tuple[str, str]] = [
    ("driver_profiles",        _DRIVER_PROFILES_TABLE),
    ("driver_progression",     _DRIVER_PROGRESSION_TABLE),
    ("driving_style_features", _DRIVING_STYLE_FEATURES_TABLE),
]

# ------------------------------------------------------------------
# Phase 4 tables (theoretical data, reference lines, G-G accel)
# ------------------------------------------------------------------

_THEORETICAL_DATA_TABLE = """
CREATE TABLE IF NOT EXISTS theoretical_data (
    session_id             TEXT PRIMARY KEY REFERENCES sessions(session_id),
    theoretical_time_s     REAL,
    actual_best_time_s     REAL,
    gap_pct                REAL,
    simulation_method      TEXT,
    speed_profile_json     TEXT,
    distance_json          TEXT,
    metrics_json           TEXT,
    corner_coaching_json   TEXT,
    delta_map_json         TEXT,
    session_scalars_json   TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_REFERENCE_LINES_TABLE = """
CREATE TABLE IF NOT EXISTS reference_lines (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL REFERENCES sessions(session_id),
    latitudes_json   TEXT    NOT NULL,
    longitudes_json  TEXT    NOT NULL,
    distances_json   TEXT    NOT NULL,
    speeds_json      TEXT,
    UNIQUE(session_id)
);
"""

PHASE_4_TABLES: list[tuple[str, str]] = [
    ("theoretical_data", _THEORETICAL_DATA_TABLE),
    ("reference_lines",  _REFERENCE_LINES_TABLE),
]

# ------------------------------------------------------------------
# Phase 5 tables (visualization — sector decomposition)
# ------------------------------------------------------------------

_SESSION_SECTORS_TABLE = """
CREATE TABLE IF NOT EXISTS session_sectors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL REFERENCES sessions(session_id),
    sector_index INTEGER NOT NULL,
    distance_m   REAL    NOT NULL,
    latitude     REAL,
    longitude    REAL,
    label        TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, sector_index)
);
"""

PHASE_5_TABLES: list[tuple[str, str]] = [
    ("session_sectors", _SESSION_SECTORS_TABLE),
]

# ------------------------------------------------------------------
# Phase 6 tables (data health, session tags, batch analysis)
# ------------------------------------------------------------------

_DATA_HEALTH_TABLE = """
CREATE TABLE IF NOT EXISTS data_health (
    session_id    TEXT PRIMARY KEY REFERENCES sessions(session_id),
    gps_quality   REAL,
    accel_quality REAL,
    channel_count INTEGER,
    missing_channels TEXT,
    data_gaps     INTEGER,
    total_samples INTEGER,
    overall_score REAL,
    report_json   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_SESSION_TAGS_TABLE = """
CREATE TABLE IF NOT EXISTS session_tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    tag        TEXT NOT NULL,
    confidence REAL,
    source     TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, tag)
);
"""

PHASE_6_TABLES: list[tuple[str, str]] = [
    ("data_health",   _DATA_HEALTH_TABLE),
    ("session_tags",  _SESSION_TAGS_TABLE),
]

# ------------------------------------------------------------------
# Phase 7 tables (corner metrics, best practices — driver coaching)
# ------------------------------------------------------------------

_CORNER_METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS corner_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    lap_number INTEGER NOT NULL,
    corner_id INTEGER NOT NULL,
    brake_point_m REAL,
    brake_intensity REAL,
    entry_speed_mps REAL,
    apex_speed_mps REAL,
    exit_speed_mps REAL,
    throttle_onset_m REAL,
    exit_accel_mps2 REAL,
    grip_utilization REAL,
    time_loss_ms REAL,
    coaching_hint TEXT,
    UNIQUE(session_id, lap_number, corner_id)
);
"""

_CORNER_BEST_PRACTICES_TABLE = """
CREATE TABLE IF NOT EXISTS corner_best_practices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL REFERENCES tracks(track_id),
    corner_id INTEGER NOT NULL,
    best_entry_mps REAL,
    best_apex_mps REAL,
    best_exit_mps REAL,
    best_brake_m REAL,
    best_throttle_onset_m REAL,
    best_time_s REAL,
    sample_count INTEGER DEFAULT 0,
    source_sessions TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(track_id, corner_id)
);
"""

_TRACK_KEY_CORNERS_TABLE = """
CREATE TABLE IF NOT EXISTS track_key_corners (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id    TEXT    NOT NULL REFERENCES tracks(track_id),
    corner_id   INTEGER NOT NULL,
    label       TEXT,
    lat         REAL,
    lon         REAL,
    dist_m      REAL,
    UNIQUE(track_id, corner_id)
);
"""

PHASE_7_TABLES: list[tuple[str, str]] = [
    ("corner_metrics",        _CORNER_METRICS_TABLE),
    ("corner_best_practices", _CORNER_BEST_PRACTICES_TABLE),
    ("track_key_corners",     _TRACK_KEY_CORNERS_TABLE),
]

# ------------------------------------------------------------------
# Phase 8 tables (advanced analytics — weather, trends, rivals)
# ------------------------------------------------------------------

_SESSION_WEATHER_TABLE = """
CREATE TABLE IF NOT EXISTS session_weather (
    session_id    TEXT PRIMARY KEY REFERENCES sessions(session_id),
    air_temp_c    REAL,
    track_temp_c  REAL,
    humidity_pct  REAL,
    wind_speed_mps REAL,
    wind_dir_deg  REAL,
    pressure_hpa  REAL,
    weather_source TEXT,
    recorded_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PHASE_8_TABLES: list[tuple[str, str]] = [
    ("session_weather", _SESSION_WEATHER_TABLE),
]

# ------------------------------------------------------------------
# Phase 9 tables (predictive & simulation)
# ------------------------------------------------------------------

_VEHICLE_SETUPS_TABLE = """
CREATE TABLE IF NOT EXISTS vehicle_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE REFERENCES sessions(session_id),
    driver_id INTEGER NOT NULL REFERENCES drivers(driver_id),
    setup_name TEXT,
    front_pressure REAL, rear_pressure REAL,
    front_camber REAL, rear_camber REAL,
    ride_height_mm REAL, spring_rate REAL,
    weight_kg REAL, fuel_load_kg REAL,
    gear_ratios_json TEXT, notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_WHAT_IF_SCENARIOS_TABLE = """
CREATE TABLE IF NOT EXISTS what_if_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    scenario_name TEXT,
    adjustments_json TEXT,
    predicted_time_s REAL,
    baseline_time_s REAL,
    delta_s REAL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

PHASE_9_TABLES: list[tuple[str, str]] = [
    ("vehicle_setups",      _VEHICLE_SETUPS_TABLE),
    ("what_if_scenarios",   _WHAT_IF_SCENARIOS_TABLE),
]

# ------------------------------------------------------------------
# Phase 10 tables (annotations, development plans, dashboards, export)
# ------------------------------------------------------------------

_SESSION_ANNOTATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS session_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    lap_number INTEGER,
    distance_m REAL,
    annotation_type TEXT NOT NULL DEFAULT 'note',
    title TEXT,
    body TEXT NOT NULL,
    tags_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_DEVELOPMENT_PLANS_TABLE = """
CREATE TABLE IF NOT EXISTS development_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER NOT NULL REFERENCES drivers(driver_id),
    plan_name TEXT NOT NULL,
    template_id TEXT,
    level TEXT NOT NULL DEFAULT 'intermediate',
    weeks_json TEXT NOT NULL,
    progress_json TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_PLAN_DRILL_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS plan_drill_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES development_plans(id),
    week_index  INTEGER NOT NULL,
    drill_index INTEGER NOT NULL,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id),
    linked_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, week_index, drill_index, session_id)
);
"""

_DRIVER_BADGES_TABLE = """
CREATE TABLE IF NOT EXISTS driver_badges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id     INTEGER NOT NULL REFERENCES drivers(driver_id),
    badge_type    TEXT NOT NULL,
    badge_name    TEXT NOT NULL,
    badge_level   TEXT,
    metadata_json TEXT,
    earned_at     TEXT NOT NULL DEFAULT (datetime('now')),
    plan_id       INTEGER REFERENCES development_plans(id)
);
"""

_CUSTOM_DASHBOARDS_TABLE = """
CREATE TABLE IF NOT EXISTS custom_dashboards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER,
    dashboard_name TEXT NOT NULL,
    layout_json TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_EXPORT_TEMPLATES_TABLE = """
CREATE TABLE IF NOT EXISTS export_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT NOT NULL UNIQUE,
    sections_json TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'pdf',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PHASE_10_TABLES: list[tuple[str, str]] = [
    ("session_annotations",   _SESSION_ANNOTATIONS_TABLE),
    ("development_plans",     _DEVELOPMENT_PLANS_TABLE),
    ("plan_drill_sessions",   _PLAN_DRILL_SESSIONS_TABLE),
    ("driver_badges",         _DRIVER_BADGES_TABLE),
    ("custom_dashboards",     _CUSTOM_DASHBOARDS_TABLE),
    ("export_templates",      _EXPORT_TEMPLATES_TABLE),
]

# ------------------------------------------------------------------
# Phase 11 tables (stint analysis)
# ------------------------------------------------------------------

_STINT_ANALYSIS_TABLE = """
CREATE TABLE IF NOT EXISTS stint_analysis (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(session_id),
    stint_number  INTEGER NOT NULL,
    lap_start     INTEGER NOT NULL,
    lap_end       INTEGER NOT NULL,
    lap_count     INTEGER NOT NULL,
    best_lap      INTEGER,
    best_time_s   REAL,
    mean_time_s   REAL,
    median_time_s REAL,
    std_time_s    REAL,
    cv_pct        REAL,
    pace_fade_pct REAL,
    tyre_cliff_lap INTEGER,
    tyre_cliff_severity_pct REAL,
    pace_trend_slope REAL,
    coaching_hint TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, stint_number)
);
"""

PHASE_11_TABLES: list[tuple[str, str]] = [
    ("stint_analysis", _STINT_ANALYSIS_TABLE),
]

# ------------------------------------------------------------------
# Phase 12 tables (streaming ingestion pipeline)
# ------------------------------------------------------------------

_INGESTION_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id          TEXT PRIMARY KEY,
    file_path       TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    sha256          TEXT,
    sha256_partial  TEXT NOT NULL,
    encoding        TEXT,
    delimiter       TEXT,
    header_idx      INTEGER,
    n_rows_total    INTEGER,
    n_rows_loaded   INTEGER DEFAULT 0,
    n_chunks        INTEGER DEFAULT 0,
    cache_dir       TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    elapsed_s       REAL
);
"""

PHASE_12_TABLES: list[tuple[str, str]] = [
    ("ingestion_jobs", _INGESTION_JOBS_TABLE),
]

# ------------------------------------------------------------------
# Phase 13 tables (predefined catalogs, user karts, track sectors)
# ------------------------------------------------------------------

_PREDEFINED_TRACKS_TABLE = """
CREATE TABLE IF NOT EXISTS predefined_tracks (
    predefined_track_id INTEGER PRIMARY KEY AUTOINCREMENT,
    country             TEXT,
    track_name          TEXT,
    city                TEXT,
    region              TEXT,
    layout_name         TEXT,
    layout_length_m     REAL,
    direction           TEXT,
    rental_available    INTEGER DEFAULT 0,
    owner_available     INTEGER DEFAULT 0,
    outdoor             INTEGER DEFAULT 1,
    data_quality        TEXT,
    source_url          TEXT
);
"""

_PREDEFINED_KARTS_TABLE = """
CREATE TABLE IF NOT EXISTS predefined_karts (
    predefined_kart_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    segment             TEXT,
    manufacturer        TEXT,
    model               TEXT,
    model_year_start    INTEGER,
    use_or_championship TEXT,
    engine              TEXT,
    power_hp            REAL,
    engine_type         TEXT,
    kart_weight_kg      REAL,
    top_speed_kmh       REAL,
    zero_to_100_s       REAL,
    power_to_weight     REAL,
    braking_g_est       REAL,
    lateral_g_est       REAL,
    weight_source       TEXT
);
"""

_KARTS_TABLE = """
CREATE TABLE IF NOT EXISTS karts (
    kart_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    predefined_kart_id  INTEGER REFERENCES predefined_karts(predefined_kart_id),
    kart_name           TEXT NOT NULL,
    manufacturer        TEXT,
    model               TEXT,
    engine              TEXT,
    power_hp            REAL,
    kart_weight_kg      REAL,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_TRACK_SECTORS_TABLE = """
CREATE TABLE IF NOT EXISTS track_sectors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id    TEXT    NOT NULL REFERENCES tracks(track_id),
    sector_index INTEGER NOT NULL,
    latitude    REAL    NOT NULL,
    longitude   REAL    NOT NULL,
    distance_m  REAL,
    label       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(track_id, sector_index)
);
"""

PHASE_13_TABLES: list[tuple[str, str]] = [
    ("predefined_tracks", _PREDEFINED_TRACKS_TABLE),
    ("predefined_karts",  _PREDEFINED_KARTS_TABLE),
    ("karts",             _KARTS_TABLE),
    ("track_sectors",     _TRACK_SECTORS_TABLE),
]

# ------------------------------------------------------------------
# Phase 14 tables (meteo geocoding cache)
# ------------------------------------------------------------------

_PREDEFINED_TRACK_COORDS_TABLE = """
CREATE TABLE IF NOT EXISTS predefined_track_coords (
    track_name   TEXT PRIMARY KEY,
    city         TEXT,
    country      TEXT DEFAULT 'FR',
    latitude     REAL,
    longitude    REAL,
    geocoded_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

PHASE_14_TABLES: list[tuple[str, str]] = [
    ("predefined_track_coords", _PREDEFINED_TRACK_COORDS_TABLE),
]

# ── Phase 15: Race Strategy (endurance race management) ──────────────

_RACE_CONFIGS_TABLE = """
CREATE TABLE IF NOT EXISTS race_configs (
    race_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    race_name           TEXT    NOT NULL,
    track_name          TEXT,
    team_name           TEXT,
    race_duration_s     INTEGER NOT NULL,
    reference_weight_kg REAL,
    desired_stints      INTEGER NOT NULL DEFAULT 4,
    fuel_autonomy_s     INTEGER,
    min_pit_stop_s      INTEGER NOT NULL DEFAULT 60,
    pit_speed_kmh       REAL,
    pit_open_s          INTEGER,
    pit_close_s         INTEGER,
    empty_kart_kg       REAL,
    full_tank_kg        REAL,
    min_total_kart_kg   REAL,
    weigh_on_pit_exit   INTEGER NOT NULL DEFAULT 0,
    qualifying_duration_s INTEGER,
    refuel_after_quali  INTEGER NOT NULL DEFAULT 0,
    mandatory_driver_change INTEGER NOT NULL DEFAULT 1,
    refueling_allowed   INTEGER NOT NULL DEFAULT 1,
    quick_pit_stop_s    INTEGER,
    race_start_ts       TEXT,
    status              TEXT    NOT NULL DEFAULT 'draft',
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_RACE_DRIVERS_TABLE = """
CREATE TABLE IF NOT EXISTS race_drivers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id             INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    driver_name         TEXT    NOT NULL,
    driver_order        INTEGER NOT NULL,
    min_stint_s         INTEGER,
    max_stint_s         INTEGER,
    min_cumulative_s    INTEGER,
    max_cumulative_s    INTEGER,
    min_rest_s          INTEGER NOT NULL DEFAULT 0,
    weight_kg           REAL,
    com_channel         TEXT,
    color_hex           TEXT
);
"""

_RACE_STINTS_TABLE = """
CREATE TABLE IF NOT EXISTS race_stints (
    stint_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id             INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_order         INTEGER NOT NULL,
    driver_id           INTEGER NOT NULL REFERENCES race_drivers(id),
    planned_start_s     INTEGER,
    planned_end_s       INTEGER,
    planned_duration_s  INTEGER,
    actual_start_s      INTEGER,
    actual_end_s        INTEGER,
    actual_duration_s   INTEGER,
    fuel_at_start       REAL,
    fuel_at_end         REAL,
    ballast_kg          REAL,
    ballast_base_kg         REAL,
    ballast_fuel_offset_kg  REAL,
    fuel_burn_rate_kgs      REAL,
    notes               TEXT,
    status              TEXT NOT NULL DEFAULT 'planned'
);
"""

_RACE_PIT_STOPS_TABLE = """
CREATE TABLE IF NOT EXISTS race_pit_stops (
    pit_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id             INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    stint_id            INTEGER REFERENCES race_stints(stint_id),
    planned_at_s        INTEGER,
    actual_at_s         INTEGER,
    duration_s          INTEGER,
    driver_change       INTEGER NOT NULL DEFAULT 1,
    refueled            INTEGER NOT NULL DEFAULT 0,
    fuel_added_kg       REAL,
    ballast_changed     INTEGER NOT NULL DEFAULT 0,
    notes               TEXT,
    pit_type            TEXT NOT NULL DEFAULT 'full'
);
"""

_RACE_WINDOWS_TABLE = """
CREATE TABLE IF NOT EXISTS race_windows (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id               INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    window_type           TEXT NOT NULL,
    label                 TEXT,
    start_s               INTEGER NOT NULL,
    end_s                 INTEGER NOT NULL,
    refuel_allowed        INTEGER NOT NULL DEFAULT 1,
    driver_change_allowed INTEGER NOT NULL DEFAULT 1,
    window_order          INTEGER NOT NULL DEFAULT 1
);
"""

PHASE_15_TABLES: list[tuple[str, str]] = [
    ("race_configs", _RACE_CONFIGS_TABLE),
    ("race_drivers", _RACE_DRIVERS_TABLE),
    ("race_stints", _RACE_STINTS_TABLE),
    ("race_pit_stops", _RACE_PIT_STOPS_TABLE),
    ("race_windows", _RACE_WINDOWS_TABLE),
]

# ------------------------------------------------------------------
# Phase 16 tables  (Tier 3: TeamTalk — race messages)
# ------------------------------------------------------------------

_RACE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS race_messages (
    msg_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id      INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    author       TEXT    NOT NULL,
    message      TEXT    NOT NULL,
    category     TEXT    DEFAULT 'general',
    created_at   TEXT    DEFAULT (datetime('now'))
);
"""

PHASE_16_TABLES: list[tuple[str, str]] = [
    ("race_messages", _RACE_MESSAGES_TABLE),
]

# ------------------------------------------------------------------
# Phase 17 tables  (Tier 6: Live Race Intelligence — neutralizations, rivals)
# ------------------------------------------------------------------

_RACE_NEUTRALIZATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS race_neutralizations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id    INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    start_s    INTEGER NOT NULL,
    end_s      INTEGER,
    reason     TEXT    NOT NULL DEFAULT 'safety_car',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_RACE_RIVALS_TABLE = """
CREATE TABLE IF NOT EXISTS race_rivals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id     INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    team_name   TEXT    NOT NULL,
    car_number  TEXT    NOT NULL,
    notes       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_RACE_RIVAL_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS race_rival_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id     INTEGER NOT NULL REFERENCES race_configs(race_id) ON DELETE CASCADE,
    rival_id    INTEGER NOT NULL REFERENCES race_rivals(id) ON DELETE CASCADE,
    event_type  TEXT    NOT NULL,
    at_s        INTEGER NOT NULL,
    detail      TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

PHASE_17_TABLES: list[tuple[str, str]] = [
    ("race_neutralizations", _RACE_NEUTRALIZATIONS_TABLE),
    ("race_rivals",          _RACE_RIVALS_TABLE),
    ("race_rival_events",    _RACE_RIVAL_EVENTS_TABLE),
]

# ------------------------------------------------------------------
# Phase 18 tables — weather per lap
# ------------------------------------------------------------------

_SESSION_WEATHER_LAPS_TABLE = """
CREATE TABLE IF NOT EXISTS session_weather_laps (
    session_id      TEXT    NOT NULL,
    lap_number      INTEGER NOT NULL,
    timestamp       TEXT,
    air_temp_c      REAL,
    humidity_pct    REAL,
    wind_speed_mps  REAL,
    wind_dir_deg    REAL,
    rain_mm         REAL,
    cloud_cover_pct REAL,
    weather_code    INTEGER,
    grip_score      REAL,
    track_state     TEXT,
    track_temp_est_c REAL,
    PRIMARY KEY (session_id, lap_number)
);
"""

PHASE_18_TABLES: list[tuple[str, str]] = [
    ("session_weather_laps", _SESSION_WEATHER_LAPS_TABLE),
]

# ------------------------------------------------------------------
# Phase 19 tables — Stripe webhook idempotency
# ------------------------------------------------------------------

_STRIPE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS stripe_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT    NOT NULL UNIQUE,
    type         TEXT    NOT NULL,
    processed_at TEXT,
    status       TEXT    NOT NULL,
    payload_hash TEXT    NOT NULL
);
"""

PHASE_19_TABLES: list[tuple[str, str]] = [
    ("stripe_events", _STRIPE_EVENTS_TABLE),
]

# ------------------------------------------------------------------
# Phase 20 tables — Retention audit + pseudonymization
# ------------------------------------------------------------------

_RETENTION_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS retention_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    workspace_id    INTEGER,
    subject_type    TEXT    NOT NULL,
    subject_id      TEXT    NOT NULL,
    action          TEXT    NOT NULL,
    reason          TEXT    NOT NULL,
    performed_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    actor           TEXT    NOT NULL DEFAULT 'system',
    result          TEXT    NOT NULL,
    details_json    TEXT,
    request_id      TEXT
);
"""

PHASE_20_TABLES: list[tuple[str, str]] = [
    ("retention_audit", _RETENTION_AUDIT_TABLE),
]

# Convenience: all tables across all phases (updated as phases ship).
ALL_TABLES = PHASE_1_TABLES + PHASE_2_TABLES + PHASE_3_TABLES + PHASE_4_TABLES + PHASE_5_TABLES + PHASE_6_TABLES + PHASE_7_TABLES + PHASE_8_TABLES + PHASE_9_TABLES + PHASE_10_TABLES + PHASE_11_TABLES + PHASE_12_TABLES + PHASE_13_TABLES + PHASE_14_TABLES + PHASE_15_TABLES + PHASE_16_TABLES + PHASE_17_TABLES + PHASE_18_TABLES + PHASE_19_TABLES + PHASE_20_TABLES
