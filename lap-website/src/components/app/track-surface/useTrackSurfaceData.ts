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
  /** Stage 1 Step A — literal hand-traced edge polylines (Path F renderer).
   *  Present when the track has a gt_*.geojson and the session has GPS.
   *  All four arrays are in the session's local xy frame (= mean of best
   *  lap's GPS, equirectangular — same convention as the FE's projectGPS).
   *  TrackSurface3D's dispatcher renders the literal-edge mesh when these
   *  are present; falls back to legacy spine±width ribbon otherwise. */
  left_edge_xy_local?: [number, number][] | null;
  right_edge_xy_local?: [number, number][] | null;
  /** Pre-computed per-vertex (s, n) on the spine — for 2D-field colour lookup
   *  without a JS port of FrenetFrame.xy_to_sn. */
  left_edge_sn?: [number, number][] | null;
  right_edge_sn?: [number, number][] | null;
  midline_total_length_m?: number | null;
  edge_source?: 'hand_traced_gt' | null;

  /** Stage 1 medial-axis M×K grid fields. Present when gt + medial_axis
   *  topology succeeded (annulus track). FE dispatcher renders the
   *  M×K triangulated mesh when present; falls back to literal-edge
   *  ribbon otherwise. */
  mesh_spine_xy?: [number, number][] | null;
  mesh_L_xy?: [number, number][] | null;
  mesh_R_xy?: [number, number][] | null;
  mesh_spine_s?: number[] | null;
  mesh_hw_L?: number[] | null;
  mesh_hw_R?: number[] | null;
  mesh_M?: number | null;
  mesh_K?: number | null;
  mesh_spine_source?: 'medial_axis' | 'cross_section_hand_traced' | string | null;
  // EXEC-10: mesh_grid_xy / mesh_grid_sn removed — never consumed (the FE
  // renders mesh_tri_*; the M×K fallback derives its grid from mesh_spine/L/R).
  /** Periodic-loop contract: ``mesh_s_periodic=true`` + ``mesh_lap_length_m=L``
   *  means s=L identifies s=0. The renderer's wrap ring (between station
   *  M-1 and station 0) is what makes the tube watertight. */
  mesh_s_periodic?: boolean | null;
  mesh_lap_length_m?: number | null;

  /** Constrained Delaunay triangulation — PRIMARY render path. Replaces
   *  the M×K structured grid (which inverts at apex where R_medial < hw).
   *  Per-vertex (s, n) preserved for grip-field lookup at render time.
   *  Per-vertex grip + source already attached on the producer side so
   *  the FE doesn't need to re-do the 2D/1D combine logic. The M×K and
   *  literal-edge fields stay as dispatcher fallbacks. */
  mesh_tri_xy?: [number, number][] | null;
  mesh_tri_indices?: [number, number, number][] | null;
  mesh_tri_sn?: [number, number][] | null;
  mesh_tri_grip?: number[] | null;
  /** Per-vertex grip source: "2d_combined" | "meteo_default" |
   *  "1d_fallback" | "default". Surfaces whether the producer's 2D
   *  meteo layer is actually populating values for this session. */
  mesh_tri_grip_source?: string[] | null;
  mesh_tri_grip_source_counts?: Record<string, number> | null;
  /** Per-tile MEASURED grip (mu = |a_lat|/g), aggregated across ALL of the
   *  session's laps; null where the kart never drove the tile. The honest,
   *  sparse-where-driven companion to the dense 1D `mesh_tri_grip` profile —
   *  GRIP prefers this and falls back to `mesh_tri_grip` when it's absent
   *  (no accel_lat stored / too few samples). Lap-independent. */
  mesh_tri_grip_measured?: (number | null)[] | null;
  mesh_tri_grip_measured_count?: number | null;
  mesh_tri_grip_measured_laps?: number | null;
  mesh_tri_vertex_count?: number | null;
  mesh_tri_triangle_count?: number | null;
  mesh_tri_min_signed_area_m2?: number | null;
  mesh_tri_sha256?: string | null;
  /** EXEC-7: per-vertex max speed (m/s) for the selected lap; null where the
   *  lap never drove that tile. Lap-specific (the rest of mesh_tri_* is not).
   *  mesh_tri_speed_lap echoes which lap produced it; *_max_mps is the lap max. */
  mesh_tri_speed?: (number | null)[] | null;
  mesh_tri_speed_lap?: number | null;
  mesh_tri_speed_max_mps?: number | null;
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

export function useTrackSurfaceData(sessionId: string, lap?: number | null) {
  // ?lap=N drives the lap-specific channels — SPEED colouring (mesh_tri_speed
  // is computed for the requested lap) and the driven-line overlay. Geometry
  // + grip are lap-independent but ride along on the same lap-keyed surface
  // payload. optimal-line / line-delta stay lap-agnostic.
  const lapQ = lap != null ? `?lap=${lap}` : '';

  const surface = useQuery({
    queryKey: ['track-surface', sessionId, lap ?? null],
    queryFn: () => api.get<TrackSurfaceResponse>(`/sessions/${sessionId}/track-surface${lapQ}`),
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
    queryKey: ['gps-trace-surface', sessionId, lap ?? null],
    queryFn: () => api.get<GpsTraceResponse>(`/sessions/${sessionId}/gps-trace${lapQ}`),
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
  // Same {available: false} shape detection as optimalLine / lineDelta —
  // sessions without a GPS lap return that envelope on /gps-trace, and
  // letting it leak through as a truthy object caused gpsToLocalXY in
  // the renderer's gpsXY useMemo to crash on `latitudes.length` because
  // latitudes was undefined. Filter to canonical {latitudes, longitudes,
  // distances, speeds} shape; null otherwise.
  const gpsTraceValid = gpsTrace.data && Array.isArray(
    (gpsTrace.data as { latitudes?: unknown }).latitudes,
  ) && Array.isArray(
    (gpsTrace.data as { longitudes?: unknown }).longitudes,
  )
    ? (gpsTrace.data as GpsTraceResponse)
    : null;

  return {
    surface: surface.data ?? null,
    optimalLine: optimalPoints,
    gpsTrace: gpsTraceValid,
    lineDelta: lineDeltaPoints,
    isLoading,
    error,
  };
}
