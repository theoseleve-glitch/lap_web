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
  sessions_count: number;
  best_score: number | null;
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
