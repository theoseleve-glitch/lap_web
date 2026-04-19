// AUTO-GENERATED — DO NOT EDIT BY HAND.
// Source: telemetry_tool/web/schemas/contracts/_schemas/*.schema.json
// Regenerate with:
//   python -m telemetry_tool.web.schemas.contracts._scripts.generate_ts

export interface CornerCoachingItem {
  corner_id: string;
  items?: Array<CornerCueItem>;
}

export interface CornerCueItem {
  cost_ms?: number | null;
  cue_text: string;
  phase: "entry" | "brake_release" | "apex" | "exit" | "straight";
  severity: "high" | "medium" | "low";
  weakness_key: string;
}

export interface FocusItem {
  corner_ids?: Array<string>;
  cost_ms?: number | null;
  rank: number;
  severity: "high" | "medium" | "low";
  title: string;
  weakness_key: string;
}

export interface NextRunItem {
  body: string;
  item_type: "technical_focus" | "execution_focus" | "validation_metric" | "anti_overload";
  title: string;
  weakness_key?: string | null;
}

export interface StorylineItem {
  detail?: string | null;
  headline: string;
  state: "Detected" | "NotTriggered" | "Insufficient" | "Unregistered";
  weakness_key: string;
}

export interface ValidationCheck {
  check_id: string;
  corner_id?: string | null;
  description: string;
  measurable_target?: string | null;
}

export interface CoachingContract {
  corner_coaching: Record<string, CornerCoachingItem>;
  global_focus: Array<FocusItem>;
  next_run: Array<NextRunItem>;
  not_evaluable_corners: Array<string>;
  storyline: Array<StorylineItem>;
  validation_checks: Array<ValidationCheck>;
  version?: string;
}

export interface CornerDelta {
  coaching_text?: string;
  corner_id: string;
  phase?: string | null;
  root_cause: string;
  time_loss_s: number;
}

export type OptimizerDepth =
  | "trajectory_only"
  | "full_fidelity";

export interface ReconstructedInputs {
  brake: Array<number>;
  distance_m: Array<number>;
  steer: Array<number>;
  throttle: Array<number>;
}

export interface TrajectoryDelta {
  distance_m: Array<number>;
  speed_delta_ms: Array<number>;
}

export interface OptimizerContract {
  /** Overall result confidence, 0..1 */
  confidence: number;
  corner_deltas?: Array<CornerDelta>;
  depth: OptimizerDepth;
  /** Underlying solver identifier, e.g. 'qss_enhanced' or 'trajectory' */
  method: string;
  reconstructed_inputs?: ReconstructedInputs | null;
  theoretical_lap_time_s: number;
  total_time_loss_s?: number;
  trajectory_delta?: TrajectoryDelta | null;
  validation?: Record<string, unknown>;
  /** Identified model params, free-form until W5 */
  vehicle_model?: Record<string, unknown>;
}

export type ChannelTag =
  | "gps"
  | "lat_g"
  | "lon_g"
  | "yaw_rate"
  | "throttle"
  | "brake"
  | "steer"
  | "wheel_spd"
  | "shock_defl";

export interface DriverRef {
  driver_id: number;
  name: string;
}

export interface Event {
  detector?: string | null;
  event_type: string;
  lap_number?: number | null;
  payload?: Record<string, unknown>;
  s_m?: number | null;
  severity?: string | null;
  t_s?: number | null;
}

export interface LapSummary {
  flags?: Array<string>;
  is_best?: boolean;
  is_valid?: boolean;
  lap_number: number;
  /** None for incomplete laps */
  lap_time_s?: number | null;
}

export interface Scores {
  consistency: number;
  execution: number;
  overall: number;
  pace: number;
  robustness: number;
}

export interface SessionCapabilities {
  channels?: Array<ChannelTag>;
}

export interface SidecarRef {
  format?: string;
  object_key: string;
  sha256?: string | null;
  size_bytes?: number | null;
}

export type SourceLiteral =
  | "real_life"
  | "iracing"
  | "ac";

export interface TrackRef {
  layout?: string | null;
  name: string;
  track_id: number;
}

export interface VehicleRef {
  model?: string | null;
  vehicle_class?: string | null;
  vehicle_id?: number | null;
}

export interface SessionContract {
  capabilities: SessionCapabilities;
  contract_version?: string;
  /** Free-form dict describing how the file was detected + parsed. Shape defined by W2 (profiler). */
  data_profile?: Record<string, unknown>;
  driver: DriverRef;
  duration_s: number;
  events?: Array<Event>;
  laps?: Array<LapSummary>;
  scores?: Scores | null;
  session_id: string;
  session_start: string;
  /** Pointer to raw-channel Parquet sidecar. Absent until W9 storage lands. */
  sidecar?: SidecarRef | null;
  source: SourceLiteral;
  track: TrackRef;
  vehicle: VehicleRef;
  workspace_id: string;
}
