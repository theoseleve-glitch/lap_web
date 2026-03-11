export interface FocusArea {
  rank: number;
  category: string;
  time_loss_s: number;
  corner_ids: number[];
  summary: string;
  advice: string;
  progressive_steps?: string[] | null;
  symptom_diagnosis?: string | null;
}

export interface Drill {
  title: string;
  description?: string;
  difficulty_progression?: {
    beginner?: { description: string; success_criteria: string; lap_count: number };
    intermediate?: { description: string; success_criteria: string; lap_count: number };
    advanced?: { description: string; success_criteria: string; lap_count: number };
  } | null;
}

export interface ProgressionInsight {
  metric: string;
  trend: string;
  detail?: string;
}

export interface SpeedTarget {
  phase: 'entry' | 'apex' | 'exit';
  actual_kph: number;
  target_kph: number;
}

export interface TractionBudget {
  corner_id: number;
  entry_grip?: number | null;
  apex_grip?: number | null;
  exit_grip?: number | null;
}

export interface TrailBrakeData {
  corner_id: number;
  throttle_m?: number | null;
  straight_brake_m?: number | null;
  trail_brake_m?: number | null;
  transition_m?: number | null;
  overlap_m?: number | null;
}

export interface ExitCascade {
  corner_id: number;
  corner_name?: string | null;
  exit_speed_delta_kph?: number | null;
  straight_time_loss_s?: number | null;
  total_cascade_s?: number | null;
}

export interface CornerCoachingDetail {
  corner_id: number;
  corner_name?: string | null;
  primary_cause?: string | null;
  time_loss_s?: number | null;
  coaching_tip?: string | null;
  progressive_steps?: string[] | null;
  speed_targets?: SpeedTarget[] | null;
  traction_budget?: TractionBudget | null;
  trail_brake?: TrailBrakeData | null;
  exit_cascade?: ExitCascade | null;
  apex_speed_history?: number[] | null;
  sessions_tracked?: number | null;
  trend_direction?: 'improving' | 'declining' | 'stable' | null;
}

export interface WarmUpProtocol {
  steps?: string[] | null;
  duration_minutes?: number | null;
}

export interface CoachingV3Data {
  session_theme: string;
  narrative: string;
  strengths: string[];
  weaknesses: string[];
  focus_areas: FocusArea[];
  drills: Drill[];
  progression: ProgressionInsight[];
  next_session_goals: string[];
  confidence: number;
  corner_coaching?: CornerCoachingDetail[] | null;
  trail_brake_assessment?: TrailBrakeData[] | null;
  traction_budgets?: TractionBudget[] | null;
  exit_speed_cascades?: ExitCascade[] | null;
  warm_up_protocol?: WarmUpProtocol | null;
  vehicle_class?: string | null;
  deferred_focus_areas?: FocusArea[] | null;
  late_apex_reset?: string | null;
  mental_imagery_prompts?: string[] | null;
}
