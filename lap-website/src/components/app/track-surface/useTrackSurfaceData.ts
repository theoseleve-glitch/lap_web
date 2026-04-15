'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';

/* ── API response types ───────────────────────────────── */

export interface SurfaceBin {
  distance_m: number;
  grip_mu: number;
  elevation_m: number;
  width_m?: number;
}

export interface TrackSurfaceResponse {
  bins: SurfaceBin[];
  quality_tier?: string;
}

export interface OptimalLinePoint {
  distance_m: number;
  speed_mps: number;
  lateral_offset_m: number;
}

export interface OptimalLineResponse {
  points: OptimalLinePoint[];
}

export interface GpsTraceResponse {
  latitudes: number[];
  longitudes: number[];
  speeds: number[];
  distances: number[];
}

export interface LineDeltaPoint {
  distance_m: number;
  actual_offset_m: number;
  optimal_offset_m: number;
  delta_m: number;
}

export interface LineDeltaResponse {
  points: LineDeltaPoint[];
  corner_coaching?: unknown[];
}

/* ── Hook ─────────────────────────────────────────────── */

const STALE = 5 * 60 * 1000;

export function useTrackSurfaceData(sessionId: string) {
  const surface = useQuery({
    queryKey: ['track-surface', sessionId],
    queryFn: () => api.get<TrackSurfaceResponse>(`/sessions/${sessionId}/track-surface`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const optimalLine = useQuery({
    queryKey: ['optimal-line', sessionId],
    queryFn: () => api.get<OptimalLineResponse>(`/sessions/${sessionId}/optimal-line`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const gpsTrace = useQuery({
    queryKey: ['gps-trace-surface', sessionId],
    queryFn: () => api.get<GpsTraceResponse>(`/sessions/${sessionId}/gps-trace`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const lineDelta = useQuery({
    queryKey: ['line-delta', sessionId],
    queryFn: () => api.get<LineDeltaResponse>(`/sessions/${sessionId}/line-delta`),
    staleTime: STALE,
    enabled: !!sessionId,
  });

  const isLoading = surface.isLoading;
  const error = surface.error ?? optimalLine.error ?? gpsTrace.error ?? lineDelta.error ?? null;

  return {
    surface: surface.data ?? null,
    optimalLine: optimalLine.data?.points ?? null,
    gpsTrace: gpsTrace.data ?? null,
    lineDelta: lineDelta.data?.points ?? null,
    isLoading,
    error,
  };
}
