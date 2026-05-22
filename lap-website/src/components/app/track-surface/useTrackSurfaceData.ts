'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';

/* ── API response types ───────────────────────────────── */

export interface SurfaceBin {
  distance_m: number;
  /** Per-bin 95th-percentile lateral mu — the canonical surface channel for
   *  the GRIP colormap. API key: `mu_lat_p95`. */
  mu_lat_p95: number;
  /** Per-bin mean lateral mu — companion read for diagnostics / future
   *  channel selector. API key: `mu_lat_mean`. */
  mu_lat_mean: number;
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

/** Day-12 1D per-arclength spatial μ modifier + Day-13 Phase D optional
 *  2D per-tile fields.
 *
 *  1D layer (Day 12) — five aligned per-segment arrays (length N_s =
 *  number of Frenet segments): the combined factor + the three
 *  components (drainage, sun, wind). Authoritative for the diagnostic
 *  panel readouts + the arc-length summary.
 *
 *  2D layer (Day 13 Phase D) — when ``elevation_surface`` was available
 *  on the producer side, flat row-major lists (length M_s × M_n) for
 *  each factor + the combined product. Drive per-tile cross-track
 *  coloring on the 3D mesh. Absent (undefined or null) when the
 *  producer didn't have a z(s, n) substrate — the renderer falls back
 *  to per-bin longitudinal bands keyed on the 1D arrays.
 *
 *  Substrate note: the producer routes around the noisy camber_rad
 *  estimator (±48° spikes on flat kart tracks). See CLEANUP_LOG.md
 *  Day 13 deferred investigation.
 */
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
  // Day-13 Phase D — optional 2D per-tile fields. Flat row-major;
  // index a tile (i_s, j_n) at flat[i_s * M_n + j_n].
  drainage_field_2d?: number[] | null;
  sun_field_2d?: number[] | null;
  wind_field_2d?: number[] | null;
  factor_field_2d?: number[] | null;
  tile_arclength_samples?: number[] | null;
  tile_lateral_offsets?: number[] | null;
  /** (M_s, M_n) — longitudinal × lateral cell counts for the 2D grid. */
  tile_grid_shape?: [number, number] | null;
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

  // Day-14: only the surface query's error trips the panel-level error
  // state. Missing optimal-line / line-delta is the common case for a
  // new user's first upload (no aggregate surface yet, no kart vehicle
  // profile) and now returns 200 + {available:false} from the API. The
  // panel must degrade gracefully — render surface + conditions, omit
  // the optimal/delta overlays — rather than show "Failed to load".
  // gps-trace already had this shape and was never rolled up as a hard
  // error; aligning optimal-line + line-delta to the same pattern.
  const error = surface.error ?? null;

  // Endpoints with {available: false} payloads return that shape rather
  // than the canonical {points: [...]} shape. Detect via the `points`
  // key presence so the consumer sees null instead of an unexpected
  // available-flag object.
  const optimalPoints = optimalLine.data && Array.isArray(
    (optimalLine.data as { points?: unknown }).points,
  )
    ? (optimalLine.data as OptimalLineResponse).points
    : null;
  const lineDeltaPoints = lineDelta.data && Array.isArray(
    (lineDelta.data as { points?: unknown }).points,
  )
    ? (lineDelta.data as LineDeltaResponse).points
    : null;

  return {
    surface: surface.data ?? null,
    optimalLine: optimalPoints,
    gpsTrace: gpsTrace.data ?? null,
    lineDelta: lineDeltaPoints,
    isLoading,
    error,
  };
}
