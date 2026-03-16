export interface Stint {
  stint_number: number;
  start_lap: number;
  end_lap: number;
  lap_count: number;
  pit_lap_number: number | null;
  pit_lap_time_s: number | null;
  condition: string | null;
  driver_name: string | null;
  driver_id: number | null;
  best_lap_s?: number;
  mean_lap_s?: number;
  consistency_cv_pct?: number;
  pace_fade_pct?: number;
  scores?: { pace: number; consistency: number; robustness: number };
}

export interface StintAssignment {
  stint_number: number;
  driver_name?: string;
  driver_id?: number;
  condition?: string;
}

export interface DriverReport {
  driver_name: string;
  total_laps: number;
  total_stints: number;
  stints: Stint[];
  best_lap_s: number;
  mean_lap_s: number;
  consistency_cv_pct: number;
  best_per_stint: { stint_number: number; best_lap_s: number }[];
  scores: { pace: number; consistency: number; robustness: number };
}

export interface TeamReport {
  total_laps: number;
  total_time_s: number | null;
  total_stints: number;
  drivers: string[];
  driver_comparison: DriverReport[];
  scores: { pace: number; consistency: number; robustness: number };
}

export type EnduranceTier = 'team' | 'driver' | 'stint';

export interface EnduranceReportResponse {
  team: TeamReport;
  drivers: Record<string, DriverReport>;
  stints: Record<number, Stint>;
}

export interface StintsResponse {
  stints: Stint[];
  pit_threshold_s: number;
  total_stints: number;
}

export const CONDITIONS = ['dry', 'damp', 'wet', 'mixed'] as const;
export type Condition = typeof CONDITIONS[number];

export const DRIVER_COLORS = [
  '#B6FF2E', '#00d4ff', '#D946EF', '#FF6A00', '#FFD400',
  '#FF3B6B', '#00E5A0', '#8B5CF6',
] as const;
