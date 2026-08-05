"""
Named SQL query constants.

Keeping queries here (rather than inline in route handlers) makes
them easy to audit, test, and reuse.
"""

# ------------------------------------------------------------------
# Sessions
# ------------------------------------------------------------------

INSERT_SESSION = """
INSERT OR REPLACE INTO sessions (
    session_id, csv_filename, driver_id, track_id,
    session_type, track_state, session_date,
    n_laps, best_lap_time_s, mean_lap_time_s,
    total_score, grade, weather_json, notes,
    html_report_path, simulation_method, joker_lap_number,
    display_name, source_filename, source_path, kart_id,
    channel_inventory, data_tier, available_channels,
    source_format, source_metadata,
    pipeline_version_hash, model_version
) VALUES (
    :session_id, :csv_filename, :driver_id, :track_id,
    :session_type, :track_state, :session_date,
    :n_laps, :best_lap_time_s, :mean_lap_time_s,
    :total_score, :grade, :weather_json, :notes,
    :html_report_path, :simulation_method, :joker_lap_number,
    :display_name, :source_filename, :source_path, :kart_id,
    :channel_inventory, :data_tier, :available_channels,
    :source_format, :source_metadata,
    :pipeline_version_hash, :model_version
);
"""

SELECT_SESSIONS = """
SELECT s.*, d.driver_name, t.track_name, k.kart_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
LEFT JOIN karts k ON s.kart_id = k.kart_id
WHERE s.deleted_at IS NULL
ORDER BY s.session_date DESC
LIMIT :limit OFFSET :offset;
"""

SELECT_SESSION_BY_ID = """
SELECT s.*, d.driver_name, t.track_name, k.kart_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
LEFT JOIN karts k ON s.kart_id = k.kart_id
WHERE s.session_id = :session_id AND s.deleted_at IS NULL;
"""

SELECT_SESSION_BY_ID_ANY = """
SELECT s.*, d.driver_name, t.track_name, k.kart_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
LEFT JOIN karts k ON s.kart_id = k.kart_id
WHERE s.session_id = :session_id;
"""

COUNT_SESSIONS = """
SELECT COUNT(*) FROM sessions WHERE deleted_at IS NULL;
"""

# ------------------------------------------------------------------
# Drivers
# ------------------------------------------------------------------

UPSERT_DRIVER = """
INSERT INTO drivers (driver_name)
VALUES (:driver_name)
ON CONFLICT(driver_name) DO NOTHING;
"""

SELECT_DRIVER_BY_NAME = """
SELECT driver_id, driver_name, created_at, notes
FROM drivers
WHERE driver_name = :driver_name;
"""

SELECT_ALL_DRIVERS = """
SELECT d.driver_id, d.driver_name, d.created_at, d.notes,
       COUNT(s.session_id) AS session_count,
       MIN(s.best_lap_time_s) AS personal_best_s,
       AVG(s.total_score) AS mean_score
FROM drivers d
LEFT JOIN sessions s ON d.driver_id = s.driver_id AND s.deleted_at IS NULL
GROUP BY d.driver_id
ORDER BY d.driver_name;
"""

# ------------------------------------------------------------------
# Tracks
# ------------------------------------------------------------------

UPSERT_TRACK = """
INSERT INTO tracks (
    track_id, track_name, lap_length_m,
    bbox_lat_min, bbox_lat_max, bbox_lon_min, bbox_lon_max,
    start_lat, start_lon, sample_count, lap_count,
    has_joker, joker_distance_delta_m, joker_time_delta_s
) VALUES (
    :track_id, :track_name, :lap_length_m,
    :bbox_lat_min, :bbox_lat_max, :bbox_lon_min, :bbox_lon_max,
    :start_lat, :start_lon, :sample_count, :lap_count,
    :has_joker, :joker_distance_delta_m, :joker_time_delta_s
)
ON CONFLICT(track_id) DO UPDATE SET
    track_name   = CASE
                     WHEN tracks.track_name LIKE '%nknown%'
                       OR tracks.track_name = tracks.track_id
                     THEN excluded.track_name
                     ELSE tracks.track_name
                   END,
    lap_length_m = excluded.lap_length_m,
    updated_at   = datetime('now');
"""

UPDATE_TRACK_JOKER = """
UPDATE tracks
SET has_joker = :has_joker,
    joker_distance_delta_m = :joker_distance_delta_m,
    joker_time_delta_s = :joker_time_delta_s,
    updated_at = datetime('now')
WHERE track_id = :track_id;
"""

SELECT_ALL_TRACKS = """
SELECT t.*,
       COUNT(s.session_id) AS session_count,
       MIN(s.best_lap_time_s) AS best_time_s,
       COALESCE(SUM(s.n_laps), 0) AS lap_count
FROM tracks t
LEFT JOIN sessions s ON t.track_id = s.track_id AND s.deleted_at IS NULL
GROUP BY t.track_id
ORDER BY t.track_name;
"""

SELECT_TRACK_BY_ID = """
SELECT * FROM tracks WHERE track_id = :track_id;
"""

# ------------------------------------------------------------------
# Laps
# ------------------------------------------------------------------

INSERT_LAP = """
INSERT OR REPLACE INTO laps (
    session_id, lap_number, lap_time_s,
    speed_mean_mps, speed_max_mps,
    braking_max_mps2, accel_max_mps2, line_length_m,
    is_valid, is_best, phase_id, invalid_reason, is_joker
) VALUES (
    :session_id, :lap_number, :lap_time_s,
    :speed_mean_mps, :speed_max_mps,
    :braking_max_mps2, :accel_max_mps2, :line_length_m,
    :is_valid, :is_best, :phase_id, :invalid_reason, :is_joker
);
"""

SELECT_LAPS_FOR_SESSION = """
SELECT * FROM laps
WHERE session_id = :session_id
ORDER BY lap_number;
"""

# ------------------------------------------------------------------
# GPS traces
# ------------------------------------------------------------------

INSERT_GPS_TRACE = """
INSERT OR REPLACE INTO gps_traces (
    session_id, lap_number,
    latitudes_json, longitudes_json,
    distances_json, speeds_json,
    accel_lat_json, accel_long_json,
    throttle_json, brake_json, steering_json,
    rpm_json, gear_json,
    tire_temp_json, tire_pressure_json,
    brake_temp_json, wheel_slip_json, fuel_json
) VALUES (
    :session_id, :lap_number,
    :latitudes_json, :longitudes_json,
    :distances_json, :speeds_json,
    :accel_lat_json, :accel_long_json,
    :throttle_json, :brake_json, :steering_json,
    :rpm_json, :gear_json,
    :tire_temp_json, :tire_pressure_json,
    :brake_temp_json, :wheel_slip_json, :fuel_json
);
"""

SELECT_GPS_TRACE = """
SELECT latitudes_json, longitudes_json, distances_json, speeds_json,
       accel_lat_json, accel_long_json
FROM gps_traces
WHERE session_id = :session_id AND lap_number = :lap_number;
"""

SELECT_GPS_TRACE_CHANNELS = """
SELECT throttle_json, brake_json, steering_json,
       rpm_json, gear_json,
       tire_temp_json, tire_pressure_json,
       brake_temp_json, wheel_slip_json, fuel_json,
       distances_json, speeds_json
FROM gps_traces
WHERE session_id = :session_id AND lap_number = :lap_number;
"""

SELECT_GPS_LAPS_FOR_SESSION = """
SELECT lap_number FROM gps_traces
WHERE session_id = :session_id
ORDER BY lap_number;
"""

# ------------------------------------------------------------------
# Score details
# ------------------------------------------------------------------

INSERT_SCORE_DETAILS = """
INSERT OR REPLACE INTO score_details (
    session_id,
    pace_score, pace_max,
    consistency_score, consistency_max,
    execution_score, execution_max,
    robustness_score, robustness_max,
    strengths_json, weaknesses_json,
    adaptation_score
) VALUES (
    :session_id,
    :pace_score, :pace_max,
    :consistency_score, :consistency_max,
    :execution_score, :execution_max,
    :robustness_score, :robustness_max,
    :strengths_json, :weaknesses_json,
    :adaptation_score
);
"""

SELECT_SCORE_DETAILS = """
SELECT * FROM score_details
WHERE session_id = :session_id;
"""

# ------------------------------------------------------------------
# Condition phases
# ------------------------------------------------------------------

INSERT_CONDITION_PHASE = """
INSERT OR REPLACE INTO condition_phases (
    session_id, phase_id, lap_start, lap_end,
    label, confidence, median_pace_s
) VALUES (
    :session_id, :phase_id, :lap_start, :lap_end,
    :label, :confidence, :median_pace_s
);
"""

SELECT_CONDITION_PHASES = """
SELECT * FROM condition_phases
WHERE session_id = :session_id
ORDER BY phase_id;
"""

# ------------------------------------------------------------------
# Reflection + competitors (W3)
# ------------------------------------------------------------------

UPDATE_SESSION_REFLECTION = """
UPDATE sessions SET
    result_tags                 = :result_tags,
    driver_perceived_conditions = :driver_perceived_conditions,
    felt_performance_rating     = :felt_performance_rating,
    race_position               = :race_position,
    race_total_competitors      = :race_total_competitors,
    race_gap_to_leader_s        = :race_gap_to_leader_s,
    race_gap_to_nearest_s       = :race_gap_to_nearest_s,
    race_laps_completed         = :race_laps_completed,
    race_is_dnf                 = :race_is_dnf
WHERE session_id = :session_id;
"""

SELECT_SESSION_REFLECTION = """
SELECT result_tags, driver_perceived_conditions, felt_performance_rating,
       race_position, race_total_competitors, race_gap_to_leader_s,
       race_gap_to_nearest_s, race_laps_completed, race_is_dnf
FROM sessions WHERE session_id = :session_id;
"""

INSERT_SESSION_COMPETITOR = """
INSERT INTO session_competitors (
    session_id, competitor_name, final_position, gap_to_this_driver_s, notes
) VALUES (
    :session_id, :competitor_name, :final_position, :gap_to_this_driver_s, :notes
);
"""

SELECT_SESSION_COMPETITORS = """
SELECT id, competitor_name, final_position, gap_to_this_driver_s, notes
FROM session_competitors
WHERE session_id = :session_id
ORDER BY final_position IS NULL, final_position, id;
"""

DELETE_SESSION_COMPETITORS = """
DELETE FROM session_competitors WHERE session_id = :session_id;
"""

# ------------------------------------------------------------------
# Dashboard aggregates
# ------------------------------------------------------------------

DASHBOARD_STATS = """
SELECT
    COUNT(DISTINCT s.session_id)  AS total_sessions,
    COUNT(DISTINCT s.driver_id)   AS total_drivers,
    COUNT(DISTINCT s.track_id)    AS total_tracks,
    SUM(s.n_laps)                 AS total_laps,
    AVG(s.total_score)            AS avg_score,
    MAX(s.total_score)            AS best_score,
    MIN(s.best_lap_time_s)        AS overall_best_time_s
FROM sessions s
WHERE s.deleted_at IS NULL;
"""

# ------------------------------------------------------------------
# Weekends
# ------------------------------------------------------------------

INSERT_WEEKEND = """
INSERT INTO weekends (name, track_id, start_date, end_date, notes)
VALUES (:name, :track_id, :start_date, :end_date, :notes)
RETURNING weekend_id;
"""

UPDATE_WEEKEND = """
UPDATE weekends
SET name = :name, track_id = :track_id,
    start_date = :start_date, end_date = :end_date,
    notes = :notes
WHERE weekend_id = :weekend_id;
"""

DELETE_WEEKEND = """
DELETE FROM weekends WHERE weekend_id = :weekend_id;
"""

SELECT_ALL_WEEKENDS = """
SELECT w.*, t.track_name,
       COUNT(ws.session_id) AS session_count
FROM weekends w
LEFT JOIN tracks t ON w.track_id = t.track_id
LEFT JOIN weekend_sessions ws ON w.weekend_id = ws.weekend_id
GROUP BY w.weekend_id, t.track_id, t.track_name
ORDER BY w.start_date DESC;
"""

SELECT_WEEKEND_BY_ID = """
SELECT w.*, t.track_name
FROM weekends w
LEFT JOIN tracks t ON w.track_id = t.track_id
WHERE w.weekend_id = :weekend_id;
"""

# ------------------------------------------------------------------
# Weekend sessions (join table)
# ------------------------------------------------------------------

INSERT_WEEKEND_SESSION = """
INSERT OR REPLACE INTO weekend_sessions (weekend_id, session_id, session_order)
VALUES (:weekend_id, :session_id, :session_order);
"""

DELETE_WEEKEND_SESSION = """
DELETE FROM weekend_sessions
WHERE weekend_id = :weekend_id AND session_id = :session_id;
"""

DELETE_ALL_WEEKEND_SESSIONS = """
DELETE FROM weekend_sessions WHERE weekend_id = :weekend_id;
"""

SELECT_WEEKEND_SESSIONS = """
SELECT s.*, d.driver_name, t.track_name, ws.session_order
FROM weekend_sessions ws
JOIN sessions s ON ws.session_id = s.session_id
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
WHERE ws.weekend_id = :weekend_id AND s.deleted_at IS NULL
ORDER BY ws.session_order, s.session_date;
"""

# ------------------------------------------------------------------
# Track records
# ------------------------------------------------------------------

UPSERT_TRACK_RECORD = """
INSERT INTO track_records (
    track_id, record_time_s, record_holder,
    record_date, vehicle_class, source
) VALUES (
    :track_id, :record_time_s, :record_holder,
    :record_date, :vehicle_class, :source
)
ON CONFLICT(track_id, vehicle_class) DO UPDATE SET
    record_time_s  = excluded.record_time_s,
    record_holder  = excluded.record_holder,
    record_date    = excluded.record_date,
    source         = excluded.source;
"""

DELETE_TRACK_RECORD = """
DELETE FROM track_records WHERE id = :id;
"""

SELECT_TRACK_RECORDS = """
SELECT * FROM track_records
WHERE track_id = :track_id
ORDER BY record_time_s;
"""

# ------------------------------------------------------------------
# Condition markers (manual overrides)
# ------------------------------------------------------------------

INSERT_CONDITION_MARKER = """
INSERT OR REPLACE INTO condition_markers (
    session_id, lap_number, new_state, notes
) VALUES (
    :session_id, :lap_number, :new_state, :notes
);
"""

SELECT_CONDITION_MARKERS = """
SELECT * FROM condition_markers
WHERE session_id = :session_id
ORDER BY lap_number;
"""

# ------------------------------------------------------------------
# Cross-session queries
# ------------------------------------------------------------------

SELECT_SESSIONS_FOR_TRACK = """
SELECT s.*, d.driver_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
WHERE s.track_id = :track_id AND s.deleted_at IS NULL
ORDER BY s.session_date DESC;
"""

SELECT_SESSIONS_FOR_DRIVER = """
SELECT s.*, t.track_name
FROM sessions s
LEFT JOIN tracks t ON s.track_id = t.track_id
WHERE s.driver_id = :driver_id AND s.deleted_at IS NULL
ORDER BY s.session_date DESC;
"""

SELECT_COMPARABLE_SESSIONS = """
SELECT s.*, d.driver_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
WHERE s.track_id = :track_id
  AND s.session_id != :session_id
  AND s.deleted_at IS NULL
ORDER BY s.session_date DESC
LIMIT :limit;
"""

SELECT_HISTORICAL_BEST_TIMES = """
SELECT s.session_id, s.session_date, s.best_lap_time_s,
       s.total_score, s.track_state, d.driver_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
WHERE s.track_id = :track_id
  AND s.best_lap_time_s IS NOT NULL
  AND s.deleted_at IS NULL
ORDER BY s.best_lap_time_s;
"""

# ------------------------------------------------------------------
# Driver profiles (Phase 3)
# ------------------------------------------------------------------

UPSERT_DRIVER_PROFILE = """
INSERT INTO driver_profiles (
    driver_id, weight_kg, kart_class, experience_level,
    goals, preferred_tracks, custom_notes,
    email, phone, id_code,
    pace_delta_mean_s, consistency_rating, aggression_index,
    smoothness_index, improvement_trend,
    total_sessions, total_laps,
    best_ever_time_s, best_ever_track_id,
    wet_skill_proxy, updated_at
) VALUES (
    :driver_id, :weight_kg, :kart_class, :experience_level,
    :goals, :preferred_tracks, :custom_notes,
    :email, :phone, :id_code,
    :pace_delta_mean_s, :consistency_rating, :aggression_index,
    :smoothness_index, :improvement_trend,
    :total_sessions, :total_laps,
    :best_ever_time_s, :best_ever_track_id,
    :wet_skill_proxy, datetime('now')
)
ON CONFLICT(driver_id) DO UPDATE SET
    weight_kg          = COALESCE(excluded.weight_kg, driver_profiles.weight_kg),
    kart_class         = COALESCE(excluded.kart_class, driver_profiles.kart_class),
    experience_level   = COALESCE(excluded.experience_level, driver_profiles.experience_level),
    goals              = COALESCE(excluded.goals, driver_profiles.goals),
    preferred_tracks   = COALESCE(excluded.preferred_tracks, driver_profiles.preferred_tracks),
    custom_notes       = COALESCE(excluded.custom_notes, driver_profiles.custom_notes),
    email              = COALESCE(excluded.email, driver_profiles.email),
    phone              = COALESCE(excluded.phone, driver_profiles.phone),
    id_code            = COALESCE(excluded.id_code, driver_profiles.id_code),
    pace_delta_mean_s  = excluded.pace_delta_mean_s,
    consistency_rating = excluded.consistency_rating,
    aggression_index   = excluded.aggression_index,
    smoothness_index   = excluded.smoothness_index,
    improvement_trend  = excluded.improvement_trend,
    total_sessions     = excluded.total_sessions,
    total_laps         = excluded.total_laps,
    best_ever_time_s   = excluded.best_ever_time_s,
    best_ever_track_id = excluded.best_ever_track_id,
    wet_skill_proxy    = excluded.wet_skill_proxy,
    updated_at         = datetime('now');
"""

UPDATE_DRIVER_PROFILE_FIELDS = """
UPDATE driver_profiles SET {field} = :value, updated_at = datetime('now')
WHERE driver_id = :driver_id;
"""

SELECT_DRIVER_PROFILE = """
SELECT dp.*, d.driver_name
FROM driver_profiles dp
LEFT JOIN drivers d ON dp.driver_id = d.driver_id
WHERE dp.driver_id = :driver_id;
"""

# ------------------------------------------------------------------
# Driver progression (Phase 3)
# ------------------------------------------------------------------

INSERT_DRIVER_PROGRESSION = """
INSERT OR REPLACE INTO driver_progression (
    driver_id, session_id, session_date, track_id,
    pace_delta_s, consistency_cv_pct, aggression_index,
    smoothness_index, total_score, n_laps
) VALUES (
    :driver_id, :session_id, :session_date, :track_id,
    :pace_delta_s, :consistency_cv_pct, :aggression_index,
    :smoothness_index, :total_score, :n_laps
);
"""

SELECT_DRIVER_PROGRESSION = """
SELECT dp.*, t.track_name
FROM driver_progression dp
LEFT JOIN tracks t ON dp.track_id = t.track_id
WHERE dp.driver_id = :driver_id
ORDER BY dp.session_date;
"""

# ------------------------------------------------------------------
# Driving style features (Phase 3)
# ------------------------------------------------------------------

INSERT_DRIVING_STYLE_FEATURES = """
INSERT OR REPLACE INTO driving_style_features (
    driver_id, session_id,
    trail_braking_depth, brake_point_consistency,
    brake_pressure_buildup_rate, apex_speed_ratio,
    turn_in_aggressiveness, throttle_onset_delay_m,
    exit_acceleration_efficiency, line_variation_index,
    early_vs_late_stint_pace, smoothness_composite,
    style_label, style_confidence,
    strengths_json, weaknesses_json
) VALUES (
    :driver_id, :session_id,
    :trail_braking_depth, :brake_point_consistency,
    :brake_pressure_buildup_rate, :apex_speed_ratio,
    :turn_in_aggressiveness, :throttle_onset_delay_m,
    :exit_acceleration_efficiency, :line_variation_index,
    :early_vs_late_stint_pace, :smoothness_composite,
    :style_label, :style_confidence,
    :strengths_json, :weaknesses_json
);
"""

SELECT_DRIVING_STYLE = """
SELECT * FROM driving_style_features
WHERE driver_id = :driver_id AND session_id = :session_id;
"""

SELECT_DRIVER_STYLE_HISTORY = """
SELECT dsf.*, s.session_date
FROM driving_style_features dsf
JOIN sessions s ON dsf.session_id = s.session_id
WHERE dsf.driver_id = :driver_id AND s.deleted_at IS NULL
ORDER BY s.session_date;
"""

# ------------------------------------------------------------------
# Theoretical data (Phase 4)
# ------------------------------------------------------------------

INSERT_THEORETICAL_DATA = """
INSERT OR REPLACE INTO theoretical_data (
    session_id, theoretical_time_s, actual_best_time_s,
    gap_pct, simulation_method, speed_profile_json,
    distance_json, metrics_json,
    corner_coaching_json, delta_map_json, session_scalars_json
) VALUES (
    :session_id, :theoretical_time_s, :actual_best_time_s,
    :gap_pct, :simulation_method, :speed_profile_json,
    :distance_json, :metrics_json,
    :corner_coaching_json, :delta_map_json, :session_scalars_json
);
"""

SELECT_THEORETICAL_DATA = """
SELECT * FROM theoretical_data WHERE session_id = :session_id;
"""

# ------------------------------------------------------------------
# Reference lines (Phase 4)
# ------------------------------------------------------------------

INSERT_REFERENCE_LINE = """
INSERT OR REPLACE INTO reference_lines (
    session_id, latitudes_json, longitudes_json,
    distances_json, speeds_json
) VALUES (
    :session_id, :latitudes_json, :longitudes_json,
    :distances_json, :speeds_json
);
"""

SELECT_REFERENCE_LINE = """
SELECT latitudes_json, longitudes_json, distances_json, speeds_json
FROM reference_lines WHERE session_id = :session_id;
"""

# ------------------------------------------------------------------
# Session sectors (Phase 5 — visualization)
# ------------------------------------------------------------------

INSERT_SESSION_SECTOR = """
INSERT OR REPLACE INTO session_sectors (
    session_id, sector_index, distance_m,
    latitude, longitude, label
) VALUES (
    :session_id, :sector_index, :distance_m,
    :latitude, :longitude, :label
);
"""

SELECT_SESSION_SECTORS = """
SELECT id, session_id, sector_index, distance_m,
       latitude, longitude, label
FROM session_sectors
WHERE session_id = :session_id
ORDER BY sector_index;
"""

DELETE_SESSION_SECTOR = """
DELETE FROM session_sectors WHERE id = :id;
"""

DELETE_ALL_SESSION_SECTORS = """
DELETE FROM session_sectors WHERE session_id = :session_id;
"""

# ------------------------------------------------------------------
# Data health (Phase 6)
# ------------------------------------------------------------------

INSERT_DATA_HEALTH = """
INSERT OR REPLACE INTO data_health (
    session_id, gps_quality, accel_quality,
    channel_count, missing_channels, data_gaps,
    total_samples, overall_score, report_json
) VALUES (
    :session_id, :gps_quality, :accel_quality,
    :channel_count, :missing_channels, :data_gaps,
    :total_samples, :overall_score, :report_json
);
"""

SELECT_DATA_HEALTH = """
SELECT * FROM data_health WHERE session_id = :session_id;
"""

SELECT_ALL_DATA_HEALTH = """
SELECT dh.*, s.session_date, s.track_id, d.driver_name, t.track_name
FROM data_health dh
JOIN sessions s ON dh.session_id = s.session_id
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
WHERE s.deleted_at IS NULL
ORDER BY dh.overall_score;
"""

# ------------------------------------------------------------------
# Session tags (Phase 6)
# ------------------------------------------------------------------

INSERT_SESSION_TAG = """
INSERT OR REPLACE INTO session_tags (session_id, tag, confidence, source)
VALUES (:session_id, :tag, :confidence, :source);
"""

SELECT_SESSION_TAGS = """
SELECT * FROM session_tags
WHERE session_id = :session_id
ORDER BY tag;
"""

DELETE_SESSION_TAG = """
DELETE FROM session_tags WHERE id = :id;
"""

SELECT_SESSIONS_BY_TAG = """
SELECT s.*, d.driver_name, t.track_name, st.tag, st.confidence
FROM session_tags st
JOIN sessions s ON st.session_id = s.session_id
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
WHERE st.tag = :tag AND s.deleted_at IS NULL
ORDER BY s.session_date DESC;
"""

# ------------------------------------------------------------------
# Corner metrics (Phase 7 — driver coaching)
# ------------------------------------------------------------------

INSERT_CORNER_METRIC = """
INSERT OR REPLACE INTO corner_metrics (
    session_id, lap_number, corner_id,
    brake_point_m, brake_intensity,
    entry_speed_mps, apex_speed_mps, exit_speed_mps,
    throttle_onset_m, exit_accel_mps2,
    grip_utilization, time_loss_ms, coaching_hint,
    grip_anchor_tier, grip_anchor_reason, grip_anchor_pct, grip_anchor_baseline_g
) VALUES (
    :session_id, :lap_number, :corner_id,
    :brake_point_m, :brake_intensity,
    :entry_speed_mps, :apex_speed_mps, :exit_speed_mps,
    :throttle_onset_m, :exit_accel_mps2,
    :grip_utilization, :time_loss_ms, :coaching_hint,
    :grip_anchor_tier, :grip_anchor_reason, :grip_anchor_pct, :grip_anchor_baseline_g
);
"""

SELECT_CORNER_METRICS_FOR_SESSION = """
SELECT * FROM corner_metrics
WHERE session_id = :session_id
ORDER BY lap_number, corner_id;
"""

SELECT_CORNER_METRICS_FOR_LAP = """
SELECT * FROM corner_metrics
WHERE session_id = :session_id AND lap_number = :lap_number
ORDER BY corner_id;
"""

SELECT_CORNER_METRICS_SUMMARY = """
SELECT corner_id,
       COUNT(*) AS n_laps,
       AVG(brake_point_m) AS avg_brake_point_m,
       MIN(brake_point_m) AS min_brake_point_m,
       MAX(brake_point_m) AS max_brake_point_m,
       AVG(entry_speed_mps) AS avg_entry_speed,
       AVG(apex_speed_mps) AS avg_apex_speed,
       AVG(exit_speed_mps) AS avg_exit_speed,
       AVG(grip_utilization) AS avg_grip,
       AVG(time_loss_ms) AS avg_time_loss_ms,
       SUM(time_loss_ms) AS total_time_loss_ms
FROM corner_metrics
WHERE session_id = :session_id
GROUP BY corner_id
ORDER BY corner_id;
"""

# ------------------------------------------------------------------
# Corner best practices (Phase 7)
# ------------------------------------------------------------------

UPSERT_CORNER_BEST_PRACTICE = """
INSERT INTO corner_best_practices (
    track_id, corner_id,
    best_entry_mps, best_apex_mps, best_exit_mps,
    best_brake_m, best_throttle_onset_m, best_time_s,
    sample_count, source_sessions, updated_at
) VALUES (
    :track_id, :corner_id,
    :best_entry_mps, :best_apex_mps, :best_exit_mps,
    :best_brake_m, :best_throttle_onset_m, :best_time_s,
    :sample_count, :source_sessions, datetime('now')
)
ON CONFLICT(track_id, corner_id) DO UPDATE SET
    best_entry_mps = excluded.best_entry_mps,
    best_apex_mps = excluded.best_apex_mps,
    best_exit_mps = excluded.best_exit_mps,
    best_brake_m = excluded.best_brake_m,
    best_throttle_onset_m = excluded.best_throttle_onset_m,
    best_time_s = excluded.best_time_s,
    sample_count = excluded.sample_count,
    source_sessions = excluded.source_sessions,
    updated_at = datetime('now');
"""

SELECT_CORNER_BEST_PRACTICES = """
SELECT * FROM corner_best_practices
WHERE track_id = :track_id
ORDER BY corner_id;
"""

SELECT_CORNER_BEST_PRACTICE = """
SELECT * FROM corner_best_practices
WHERE track_id = :track_id AND corner_id = :corner_id;
"""

# ------------------------------------------------------------------
# Session weather (Phase 8 — advanced analytics)
# ------------------------------------------------------------------

INSERT_SESSION_WEATHER = """
INSERT OR REPLACE INTO session_weather (
    session_id, air_temp_c, track_temp_c, humidity_pct,
    wind_speed_mps, wind_dir_deg, pressure_hpa,
    weather_source, recorded_at
) VALUES (
    :session_id, :air_temp_c, :track_temp_c, :humidity_pct,
    :wind_speed_mps, :wind_dir_deg, :pressure_hpa,
    :weather_source, :recorded_at
);
"""

SELECT_SESSION_WEATHER = """
SELECT * FROM session_weather WHERE session_id = :session_id;
"""

SELECT_WEATHER_FOR_TRACK = """
SELECT sw.*, s.best_lap_time_s, s.session_date, s.session_type,
       d.driver_name
FROM session_weather sw
JOIN sessions s ON sw.session_id = s.session_id
LEFT JOIN drivers d ON s.driver_id = d.driver_id
WHERE s.track_id = :track_id AND s.deleted_at IS NULL
ORDER BY s.session_date;
"""

SELECT_WEATHER_FOR_DRIVER_TRACK = """
SELECT sw.*, s.best_lap_time_s, s.session_date, s.session_type
FROM session_weather sw
JOIN sessions s ON sw.session_id = s.session_id
WHERE s.track_id = :track_id AND s.driver_id = :driver_id AND s.deleted_at IS NULL
ORDER BY s.session_date;
"""

# ------------------------------------------------------------------
# Cross-session with type filtering (Phase 6)
# ------------------------------------------------------------------

SELECT_COMPARABLE_SESSIONS_TYPED = """
SELECT s.*, d.driver_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
WHERE s.track_id = :track_id
  AND s.session_id != :session_id
  AND s.session_type = :session_type
  AND s.deleted_at IS NULL
ORDER BY s.session_date DESC
LIMIT :limit;
"""

SELECT_HISTORICAL_BEST_TIMES_TYPED = """
SELECT s.session_id, s.session_date, s.best_lap_time_s,
       s.total_score, s.track_state, d.driver_name
FROM sessions s
LEFT JOIN drivers d ON s.driver_id = d.driver_id
WHERE s.track_id = :track_id
  AND s.session_type = :session_type
  AND s.best_lap_time_s IS NOT NULL
  AND s.deleted_at IS NULL
ORDER BY s.best_lap_time_s;
"""

# ------------------------------------------------------------------
# Session Annotations
# ------------------------------------------------------------------

INSERT_ANNOTATION = """
INSERT INTO session_annotations (session_id, lap_number, distance_m, annotation_type, title, body, tags_json)
VALUES (:session_id, :lap_number, :distance_m, :annotation_type, :title, :body, :tags_json);
"""

SELECT_ANNOTATIONS_FOR_SESSION = """
SELECT * FROM session_annotations WHERE session_id = :session_id ORDER BY created_at DESC;
"""

SELECT_ANNOTATION_BY_ID = """
SELECT * FROM session_annotations WHERE id = :id;
"""

UPDATE_ANNOTATION = """
UPDATE session_annotations SET title = :title, body = :body, tags_json = :tags_json,
    annotation_type = :annotation_type, lap_number = :lap_number, distance_m = :distance_m,
    updated_at = datetime('now') WHERE id = :id;
"""

DELETE_ANNOTATION = """
DELETE FROM session_annotations WHERE id = :id;
"""

SEARCH_ANNOTATIONS = """
SELECT sa.*, s.session_date, d.driver_name, t.track_name
FROM session_annotations sa
JOIN sessions s ON sa.session_id = s.session_id
LEFT JOIN drivers d ON s.driver_id = d.driver_id
LEFT JOIN tracks t ON s.track_id = t.track_id
WHERE s.deleted_at IS NULL
  AND (sa.body LIKE :query ESCAPE '\\' OR sa.title LIKE :query ESCAPE '\\' OR sa.tags_json LIKE :query ESCAPE '\\')
ORDER BY sa.created_at DESC
LIMIT :limit;
"""

SELECT_ALL_ANNOTATION_TAGS = """
SELECT DISTINCT json_each.value AS tag
FROM session_annotations, json_each(session_annotations.tags_json)
WHERE session_annotations.tags_json IS NOT NULL
ORDER BY tag;
"""

# ------------------------------------------------------------------
# Development Plans
# ------------------------------------------------------------------

INSERT_DEVELOPMENT_PLAN = """
INSERT INTO development_plans (driver_id, plan_name, template_id, level, weeks_json, progress_json)
VALUES (:driver_id, :plan_name, :template_id, :level, :weeks_json, :progress_json)
RETURNING id;
"""

SELECT_PLANS_FOR_DRIVER = """
SELECT * FROM development_plans WHERE driver_id = :driver_id ORDER BY created_at DESC;
"""

SELECT_PLAN_BY_ID = """
SELECT * FROM development_plans WHERE id = :id;
"""

UPDATE_PLAN_PROGRESS = """
UPDATE development_plans SET progress_json = :progress_json, updated_at = datetime('now') WHERE id = :id;
"""

DELETE_DEVELOPMENT_PLAN = """
DELETE FROM development_plans WHERE id = :id;
"""

# ------------------------------------------------------------------
# Custom Dashboards
# ------------------------------------------------------------------

INSERT_DASHBOARD = """
INSERT INTO custom_dashboards (driver_id, dashboard_name, layout_json, is_default)
VALUES (:driver_id, :dashboard_name, :layout_json, :is_default);
"""

SELECT_DASHBOARDS = """
SELECT * FROM custom_dashboards ORDER BY is_default DESC, updated_at DESC;
"""

SELECT_DASHBOARD_BY_ID = """
SELECT * FROM custom_dashboards WHERE id = :id;
"""

UPDATE_DASHBOARD = """
UPDATE custom_dashboards SET dashboard_name = :dashboard_name, layout_json = :layout_json,
    is_default = :is_default, updated_at = datetime('now') WHERE id = :id;
"""

DELETE_DASHBOARD = """
DELETE FROM custom_dashboards WHERE id = :id;
"""

# ------------------------------------------------------------------
# Export Templates
# ------------------------------------------------------------------

INSERT_EXPORT_TEMPLATE = """
INSERT OR REPLACE INTO export_templates (template_name, sections_json, format)
VALUES (:template_name, :sections_json, :format);
"""

SELECT_EXPORT_TEMPLATES = """
SELECT * FROM export_templates ORDER BY template_name;
"""

SELECT_EXPORT_TEMPLATE_BY_ID = """
SELECT * FROM export_templates WHERE id = :id;
"""

# ------------------------------------------------------------------
# Driving events (Phase 2 of driving-pattern-recognition, Task 10)
# ------------------------------------------------------------------

INSERT_DRIVING_EVENT = """
INSERT OR REPLACE INTO driving_events (
    session_id, lap_number, corner_id, event_type,
    s_norm_start, s_norm_end, magnitude, magnitude_unit,
    time_cost_s, validity, reason, n_samples_in_window,
    anchor_tier, anchor_reason, evidence_json
) VALUES (
    :session_id, :lap_number, :corner_id, :event_type,
    :s_norm_start, :s_norm_end, :magnitude, :magnitude_unit,
    :time_cost_s, :validity, :reason, :n_samples_in_window,
    :anchor_tier, :anchor_reason, :evidence_json
);
"""

# The ranked "what should I fix next" surface. Excludes NULL time_cost_s
# (re_braking / envelope_under_use never compute one -- see driving_events.py)
# rather than relying on ORDER BY ... DESC to push them somewhere consistent:
# SQLite sorts NULL as the smallest value (so DESC puts NULLs last) while
# PostgreSQL's default is the opposite (DESC puts NULLs first) -- filtering
# them out sidesteps that cross-dialect difference outright, and a NULL cost
# can't be ranked by cost anyway.
#
# NO `LIMIT` here (fix round 1): over_slowing and late_throttle can both
# fire on the SAME (lap_number, corner_id) with the IDENTICAL time_cost_s
# (see events_repo.get_ranked_events / _dedupe_by_lap_corner). Limiting in
# SQL happens BEFORE that dedup, so a duplicate pair could consume two of
# the caller's requested N slots and silently return fewer than N distinct
# problems. events_repo fetches every qualifying row, dedupes, THEN slices
# to the caller's limit in Python.
SELECT_RANKED_EVENTS = """
SELECT * FROM driving_events
WHERE session_id = :session_id AND time_cost_s IS NOT NULL
ORDER BY time_cost_s DESC;
"""

# Raw per-event costs for the "where am I unreliable" corner-consistency
# surface. Aggregated (best/median/worst/spread) in Python, not SQL:
# PostgreSQL has percentile_cont for median but SQLite has no built-in
# median function, so there is no single expression portable across both
# dialects this repo supports -- see events_repo.get_corner_consistency.
#
# `lap_number` is selected alongside `corner_id`/`time_cost_s` (fix round 1)
# so the repo layer can dedupe by (lap_number, corner_id) before
# aggregating -- over_slowing and late_throttle both set
# time_cost_s = corner_time - reference_corner_time for the SAME
# (lap, corner), so without the dedup a lap that fired both detectors is
# counted twice and skews median_s toward corners with more detector
# coverage rather than genuine per-lap variance.
SELECT_TIME_COSTS_FOR_CONSISTENCY = """
SELECT lap_number, corner_id, time_cost_s, anchor_tier FROM driving_events
WHERE session_id = :session_id AND time_cost_s IS NOT NULL
ORDER BY corner_id, lap_number;
"""
