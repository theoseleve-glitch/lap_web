/** Shared API response types matching the Flask backend envelope. */

export interface Session {
  id: string;
  driver_name: string;
  track_name: string;
  date: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
}

export interface Track {
  id: number;
  name: string;
  country: string;
  city: string;
  sessions_count: number;
}

export interface Driver {
  id: number;
  name: string;
  notes: string | null;
  created_at: string | null;
  session_count: number;
  personal_best_s: number | null;
  mean_score: number | null;
  has_profile: boolean;
  style_label: string | null;
  total_laps: number;
}

export interface DriverProfile {
  driver_id: number;
  driver_name: string;
  weight_kg: number | null;
  kart_class: string | null;
  experience_level: string | null;
  goals: string | null;
  preferred_tracks: string | null;
  custom_notes: string | null;
  total_sessions: number;
  total_laps: number;
  best_ever_time_s: number | null;
  best_ever_track_id: string | null;
  pace_delta_mean_s: number | null;
  consistency_rating: number | null;
  aggression_index: number | null;
  smoothness_index: number | null;
  improvement_trend: string | null;
  wet_skill_proxy: number | null;
}

export interface DriverDetail extends Driver {
  profile: DriverProfile | null;
}

export interface DriverProgression {
  session_id: string;
  session_date: string | null;
  track_id: string | null;
  track_name: string | null;
  pace_delta_s: number | null;
  consistency_cv_pct: number | null;
  aggression_index: number | null;
  smoothness_index: number | null;
  total_score: number | null;
  n_laps: number | null;
}

export interface DriverStyleEntry {
  session_id: string;
  session_date: string | null;
  style_label: string | null;
  style_confidence: number | null;
  trail_braking_depth: number | null;
  brake_point_consistency: number | null;
  brake_pressure_buildup_rate: number | null;
  apex_speed_ratio: number | null;
  turn_in_aggressiveness: number | null;
  throttle_onset_delay_m: number | null;
  exit_acceleration_efficiency: number | null;
  line_variation_index: number | null;
  early_vs_late_stint_pace: number | null;
  smoothness_composite: number | null;
  strengths: string[];
  weaknesses: string[];
}

export interface DriverBadge {
  id: number;
  badge_type: string;
  badge_name: string;
  badge_level: string | null;
  metadata_json: string | null;
  earned_at: string;
}

export interface DriverBestEver {
  best_pct: number | null;
  best_track_name: string | null;
  best_driver_time: number | null;
  best_record_time: number | null;
  best_absolute_s: number | null;
  records_held: Array<Record<string, unknown>>;
}

export interface DriverSession {
  session_id: string;
  session_date: string | null;
  best_lap_time_s: number | null;
  total_score: number | null;
  n_laps: number | null;
  track_state: string | null;
  track_name: string | null;
  track_id: string | null;
}

export interface DashboardStats {
  total_sessions: number;
  total_drivers: number;
  total_tracks: number;
  best_score: number | null;
}

export interface LapData {
  lap_number: number;
  time: number;
  speed_avg: number | null;
  valid: boolean;
}
