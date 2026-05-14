'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';

/* ── API response types ───────────────────────────────── */

export interface SurfaceBin {
  distance_m: number;
  grip_mu: number;
  elevation_m: number;
  /** Legacy total width (= width_left_m + width_right_m when both present). */
  width_m?: number;
  /** Distance from centerline to left edge, in metres. */
  width_left_m?: number;
  /** Distance from centerline to right edge, in metres. */
  width_right_m?: number;
}

export type BoundarySource =
  | 'hand_traced'
  | 'data_derived'
  | 'synthesized'
  | 'default_3m';

/** Per-session sensor quality + map confidence (RC6, Day-10).
 *
 * Populated when the pipeline producer at `track_surface.sensor_quality`
 * had enough data; `null` when it skipped (sparse data, missing IMU
 * columns, etc.). Frontend renders `null` as a grey low-confidence state
 * — never as placeholder "--". */
export interface SensorQualityBlock {
  /** Per-bin scalar in [0, 1] — sample density × excitation × calibration. */
  orientation_quality: number[];
  /** Per-bin median |a_lat| / |v^2 * kappa|. 1.0 = perfect agreement. */
  curvature_agreement: number[];
  /** Per-bin bank-angle inferred from centripetal residual, clamped to [-5, +5] deg. */
  bank_sensitivity_deg: number[];
  /** Session-aggregated attitude_correction diagnostics block. */
  attitude_correction?: Record<string, number | string | null>;
  /** Map confidence scalars + the same orientation_quality echoed
   *  under `confidence_per_bin` for backward compatibility. */
  map_confidence?: {
    excited_sample_frac: number;
    sample_density_per_bin: number;
    n_bins: number;
    confidence_per_bin: number[];
  };
}

/** Day-12 per-arclength spatial μ modifier (spec §7/§8).
 *
 * Five aligned per-segment arrays (length N_s = number of Frenet
 * segments): the combined factor + the three components (drainage from
 * slope buckets, sun from solar geometry × segment normal, wind from
 * wind direction × segment tangent). Scalar fields document the inputs
 * that produced the factors. ``mesh_source`` describes how the
 * underlying TrackSurface was built. Absent (null) when classifier ran
 * but the spatial producer skipped — e.g., safe-dry fallback or no
 * TrackSurface was available for the session. */
export interface SpatialMuModifierBlock {
  arclength_samples: number[];
  factor_values: number[];
  drainage_components: number[];
  sun_components: number[];
  wind_components: number[];
  sun_altitude_deg: number;
  sun_azimuth_deg: number;
  wind_direction_deg: number;
  wind_speed_kmh: number;
  mesh_source: 'hand_traced' | 'data_derived' | 'multihead';
  spatial_version: string;
}

/** Day-11 scalar weather classification (spec §5/§6/§8) + Day-12 spatial layer.
 *
 * Mirrors the producer's WeatherCondition dataclass minus raw_inputs
 * (debug-only reproducibility data, excluded from API contract).
 * ``source`` distinguishes weather (Open-Meteo gridded data) from user
 * (metadata override) from ml_fallback (legacy). Optional diagnostic
 * fields are omitted by the API when null (Phase B uses
 * exclude_none=True), so TS sees them as undefined. */
export interface WeatherConditionBlock {
  label: 'dry' | 'damp' | 'wet' | 'greasy';
  mu_scale: number;
  confidence: number;
  track_temp_estimate_c?: number | null;
  water_film_estimate?: 'none' | 'thin' | 'thick' | null;
  hours_since_rain?: number | null;
  days_since_significant_rain?: number | null;
  drying_rate_estimate?: number | null;
  dominant_factor: string;
  rationale: string;
  source: 'weather' | 'user' | 'ml_fallback';
  spatial_modifier?: SpatialMuModifierBlock | null;
  classifier_version: string;
}

export interface TrackSurfaceResponse {
  bins: SurfaceBin[];
  quality_tier?: string;
  boundary_source?: BoundarySource;
  /** RC6: per-session sensor quality block; null when the producer skipped. */
  sensor_quality?: SensorQualityBlock | null;
  /** Day-11/12: scalar conditions + optional nested spatial μ modifier.
   *  Absent (undefined) on pre-Day-11 sessions; the Phase B serializer
   *  omits the field rather than emitting `"conditions": null`. */
  conditions?: WeatherConditionBlock | null;
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
