'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';

/* ── Types ──────────────────────────────────────────────── */

export interface HandlingEvent {
  event_type: 'understeer' | 'oversteer';
  severity: 'mild' | 'moderate' | 'severe';
  cause: string;
  cause_detail: string;
  corner_phase: 'entry' | 'mid' | 'exit';
  magnitude: number;
  time_cost_s?: number | null;
  // New fields from multi-detector fusion
  confidence?: number | null;
  direction?: number | null;
  n_voters?: number | null;
  conflict?: boolean | null;
  detector_votes?: Record<string, { direction: number; confidence: number }> | null;
}

export interface CornerActionable {
  rank: number;
  action: string;
  impact_ms: number;
  category: string;
  phase: string;
}

export interface CornerData {
  corner_id: number;
  s_start: number;
  s_end: number;
  s_apex?: number;
  direction?: 'L' | 'R';
  available: boolean;
  entry_speed_actual?: number | null;
  entry_speed_theory?: number | null;
  apex_speed_actual?: number | null;
  apex_speed_theory?: number | null;
  exit_speed_actual?: number | null;
  exit_speed_theory?: number | null;
  time_loss_total_s?: number | null;
  grip_utilisation_pct?: number | null;
  primary_cause?: string | null;
  coaching_hint?: string | null;
  corner_type?: string | null;
  section_type?: string | null;
  exit_importance?: number | null;
  is_user_defined?: boolean | null;
  handling_events?: HandlingEvent[] | null;
  brake_release?: Record<string, unknown> | null;
  actionables?: CornerActionable[] | null;
  optimal_speeds?: number[] | null;
  optimal_time_s?: number | null;
}

export interface CornerPosition {
  corner_id: number;
  lat: number;
  lon: number;
  s_apex: number;
}

export interface GpsTrace {
  latitudes: number[];
  longitudes: number[];
  speeds: number[];
  distances: number[];
}

export interface CornerMetricRow {
  session_id: string;
  lap_number: number;
  corner_id: number;
  brake_point_m: number | null;
  apex_speed_mps: number | null;
  exit_speed_mps: number | null;
  time_loss_ms: number | null;
}

export interface TheoCorner {
  corner_id: number;
  theoretical_apex_speed_mps?: number | null;
  theoretical_entry_speed_mps?: number | null;
  theoretical_exit_speed_mps?: number | null;
  time_loss_s?: number | null;
  primary_cause?: string | null;
  coaching_hint?: string | null;
}

export interface TheoreticalData {
  available: boolean;
  reason_code?: string | null;
  theoretical_time_s: number | null;
  actual_best_time_s: number | null;
  gap_pct: number | null;
  simulation_method: string | null;
  speeds: number[];
  distances: number[];
  corner_coaching: TheoCorner[];
  delta_map_summary?: unknown[];
  session_scalars?: Record<string, unknown>;
}

export interface FocusArea {
  rank: number;
  category: string;
  time_loss_s: number;
  corner_ids: number[];
  summary: string;
  advice: string;
}

export interface CoachingData {
  focus_areas: FocusArea[];
  drills: unknown[];
  next_session_goals: string[];
  confidence: number;
}

/* ── Hook ───────────────────────────────────────────────── */

const STALE = 5 * 60 * 1000;

export function useCornerData(sessionId: string) {
  const corners = useQuery({
    queryKey: ['corners', sessionId],
    queryFn: () => api.get<{ corners: CornerData[] }>(`/sessions/${sessionId}/corners`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const positions = useQuery({
    queryKey: ['corner-positions', sessionId],
    queryFn: () => api.get<{ corners: CornerPosition[] }>(`/sessions/${sessionId}/corner-positions`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const gpsTrace = useQuery({
    queryKey: ['gps-trace-corners', sessionId],
    queryFn: () => api.get<GpsTrace>(`/sessions/${sessionId}/gps-trace`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const metrics = useQuery({
    queryKey: ['corner-metrics', sessionId],
    queryFn: () => api.get<{ corners: CornerMetricRow[]; available: boolean }>(`/sessions/${sessionId}/corner-metrics`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const theoretical = useQuery({
    queryKey: ['theoretical', sessionId],
    queryFn: () => api.get<TheoreticalData>(`/sessions/${sessionId}/theoretical`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const coaching = useQuery({
    queryKey: ['coaching', sessionId],
    queryFn: () => api.get<CoachingData>(`/sessions/${sessionId}/coaching`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const isLoading = corners.isLoading || positions.isLoading || gpsTrace.isLoading;
  const isError = corners.isError || positions.isError || gpsTrace.isError;

  function refetchAll() {
    corners.refetch();
    positions.refetch();
    gpsTrace.refetch();
    metrics.refetch();
    theoretical.refetch();
    coaching.refetch();
  }

  return {
    corners: corners.data?.corners ?? [],
    positions: positions.data?.corners ?? [],
    gpsTrace: gpsTrace.data ?? null,
    metrics: metrics.data?.corners ?? [],
    theoretical: theoretical.data ?? null,
    coaching: coaching.data ?? null,
    isLoading,
    isError,
    refetchAll,
  };
}
