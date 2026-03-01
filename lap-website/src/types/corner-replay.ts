/* Corner Replay — batch response types */

export interface CornerReplayCorner {
  corner_id: string;
  label: string;
  lat: number;
  lon: number;
  dist_m: number;
}

export interface CornerReplayLap {
  lap_number: number;
  lap_time_s: number | null;
}

export interface CornerReplayTrace {
  lat: number[];
  lon: number[];
  dist_m: number[];
  speed_mps: number[];
  accel_lat: number[];
  accel_lon: number[];
  brake?: number[];
  throttle?: number[];
  steering?: number[];
}

export interface ReplayWindow {
  lap_number: number;
  start_idx: number;
  end_idx: number;
  estimated_duration_s: number;
}

export interface CornerMetric {
  lap_number: number;
  brake_point_m: number | null;
  entry_speed_mps: number | null;
  apex_speed_mps: number | null;
  exit_speed_mps: number | null;
  time_loss_ms: number | null;
  coaching_hint: string | null;
}

export interface CornerReplayData {
  session_id: string;
  track_id: string;
  has_pedal_data: boolean;
  has_steering_data: boolean;
  corners: CornerReplayCorner[];
  laps: CornerReplayLap[];
  traces: Record<string, CornerReplayTrace>;
  replay_windows: Record<string, ReplayWindow[]>;
  corner_metrics: Record<string, CornerMetric[]>;
}

/* Orchestrator state */

export type ReplayMode = 'review' | 'split' | 'top3';
export type PlaybackSpeed = 0.25 | 0.5 | 1 | 2;

export interface ReplayState {
  mode: ReplayMode;
  cornerIndex: number;
  lapA: number;
  lapB: number;
  frame: number;
  playing: boolean;
  speed: PlaybackSpeed;
}

export type ReplayAction =
  | { type: 'SET_MODE'; mode: ReplayMode }
  | { type: 'SET_CORNER'; index: number }
  | { type: 'NEXT_CORNER'; total: number }
  | { type: 'PREV_CORNER'; total: number }
  | { type: 'SET_LAP_A'; lap: number }
  | { type: 'SET_LAP_B'; lap: number }
  | { type: 'SET_FRAME'; frame: number }
  | { type: 'TOGGLE_PLAY' }
  | { type: 'SET_SPEED'; speed: PlaybackSpeed };
