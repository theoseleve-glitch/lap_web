'use client';

import { useEffect, useMemo, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import {
  useTrackSurfaceData,
  type SurfaceBin,
  type OptimalLinePoint,
  type LineDeltaPoint,
  type WeatherConditionBlock,
} from './useTrackSurfaceData';

/* ── Heatmap palette hex values (WebGL, not CSS tokens) ── */

const COLORS = {
  grip: { high: 0x22C55E, low: 0xFF2A2A },
  // speed/gradient entries exist so the fallback-ribbon builders (no-gt /
  // provisional path) stay total over HeatmapMode — the gt Delaunay path is
  // buffer-driven and never reads these. 2-stop low→high; gradient flat ≈ mid.
  speed: { high: 0xFF2A2A, low: 0x3B82F6 },
  gradient: { high: 0xFF2A2A, low: 0x3B82F6 },
  elevation: { high: 0xF0EDE5, low: 0x3B82F6 },
  'line-delta': { high: 0x22C55E, low: 0xFF2A2A },
  'spatial-grip': { high: 0x22C55E, low: 0xFF2A2A },
} as const;

/* Day-13 Phase D: fixed color-normalization range for spatial-grip
 * effective_mu = mu_data × mu_scale × mu_spatial_factor.  Keeping the
 * range FIXED across sessions (rather than min/max-normalized) means the
 * same effective_mu always renders the same color — a wet OK session
 * reads visibly redder than a dry KCT session at the same point, which
 * is the whole point of the spatial layer. 0.5 = red anchor (severely
 * slippery), 1.0 = green anchor (baseline dry asphalt).  The 0.7 mark
 * is the spec's "driver feedback threshold" — see legend annotation. */
export const SPATIAL_GRIP_COLOR_MIN = 0.5;
export const SPATIAL_GRIP_COLOR_MAX = 1.0;
export const SPATIAL_GRIP_FEEDBACK_THRESHOLD = 0.7;
/* Confidence below this threshold dims the surface to flag low trust */
export const SPATIAL_GRIP_LOW_CONFIDENCE = 0.5;

/* Day-13 Phase E iso-factor mode: when isolating a single factor
 * (drainage / sun / wind), color-normalize across the natural producer
 * range [0.85 driest, 1.30 wettest]. Inverted from the combined view —
 * LOW factor (drier baseline) renders green, HIGH factor (water pooling
 * or shaded) renders red. Same green=more-grip semantic as Combined,
 * just sourced from a single component rather than the product. */
export const INDIVIDUAL_FACTOR_MIN = 0.85;
export const INDIVIDUAL_FACTOR_MAX = 1.30;

/** Which spatial component to isolate on the mesh under spatial-grip mode.
 *  'combined' renders the producer's clamped factor_values × mu × mu_lat_p95;
 *  'drainage'/'sun'/'wind' render that single component verbatim with
 *  the iso-factor color range applied. */
export type SpatialFactor = 'combined' | 'drainage' | 'sun' | 'wind';

const GOLD = 0xC9A84C;
const CHALK = 0xF0EDE5;
// EXEC-8: the gold "optimal" reference line is out of scope for this ship
// (Reference C). Kept wired but unmounted behind this flag.
const SHOW_OPTIMAL_LINE = false;
// Fallback widths when neither width_left_m/width_right_m nor legacy width_m
// is supplied. 4 m + 4 m matches the prior symmetric DEFAULT_TRACK_WIDTH = 8.
const DEFAULT_WIDTH_LEFT = 4;
const DEFAULT_WIDTH_RIGHT = 4;

// Visual elevation exaggeration. Real-world elevation_m values are in
// metres, but track-surface bbox is also in metres — true 1:1 z would
// be visually flat (most karting tracks have <5 m total vert range
// over a 400 m loop). Multiplier tunes how pronounced the bumps look
// in the 3D view. Applied uniformly across every builder so the
// surface, edge tubes, optimal/actual lines all sit on the same
// elevation profile.
const ELEVATION_SCALE = 2.0;

/* ── EXEC-4: colour ramp system ───────────────────────────
 * Colour is precomputed into per-mode Float32 vertex buffers and swapped
 * onto the geometry without rebuilding it. Fixed domains (not per-session
 * min/max) so a value always maps to the same colour. */
const GREY = 0x666666;
const GRIP_STOPS = [
  { t: 0.0, color: 0xFF2A2A },  // μ 0.5 — low grip (red)
  { t: 0.5, color: 0xFFD400 },  // mid (yellow)
  { t: 1.0, color: 0x22C55E },  // μ 1.1 — high grip (green)
] as const;

/* EXEC-6: GRADIENT ramp — blue (downhill) → grey (flat) → red (uphill),
 * over a symmetric domain [-G, +G]. The slope is the UNSCALED physical
 * d(elevation_m)/d(distance_m); ELEVATION_SCALE only exaggerates the z
 * geometry for visibility and must never leak into the gradient value. */
const GRADIENT_STOPS = [
  { t: 0.0, color: 0x3B82F6 },  // downhill (blue)
  { t: 0.5, color: 0xDDDDDD },  // flat (grey)
  { t: 1.0, color: 0xFF2A2A },  // uphill (red)
] as const;

/* EXEC-7: SPEED ramp — blue (slow) → green → yellow → red (fast), over the
 * lap's [min,max] finite-speed domain. null/undefined cells → grey. */
const SPEED_STOPS = [
  { t: 0.0, color: 0x3B82F6 },
  { t: 0.4, color: 0x22C55E },
  { t: 0.7, color: 0xFFD400 },
  { t: 1.0, color: 0xFF2A2A },
] as const;

/** Build an (N×3) RGB vertex buffer from scalar values via a multi-stop
 *  ramp over a fixed domain. null/NaN → grey. */
function makeColorBuffer(
  scalars: ArrayLike<number | null | undefined>,
  stops: ReadonlyArray<{ t: number; color: number }>,
  domain: readonly [number, number],
): Float32Array {
  const n = scalars.length;
  const out = new Float32Array(n * 3);
  const [d0, d1] = domain;
  const span = (d1 - d0) || 1;
  const stopColors = stops.map((s) => new THREE.Color(s.color));
  const grey = new THREE.Color(GREY);
  const tmp = new THREE.Color();
  for (let i = 0; i < n; i++) {
    const v = scalars[i];
    if (v == null || Number.isNaN(v)) {
      out[i * 3] = grey.r; out[i * 3 + 1] = grey.g; out[i * 3 + 2] = grey.b;
      continue;
    }
    let t = (v - d0) / span;
    t = Math.max(0, Math.min(1, t));
    let lo = 0;
    while (lo < stops.length - 2 && stops[lo + 1]!.t < t) lo++;
    const a = stops[lo]!; const b = stops[lo + 1]!;
    const seg = (b.t - a.t) || 1;
    const u = Math.max(0, Math.min(1, (t - a.t) / seg));
    tmp.copy(stopColors[lo]!).lerp(stopColors[lo + 1]!, u);
    out[i * 3] = tmp.r; out[i * 3 + 1] = tmp.g; out[i * 3 + 2] = tmp.b;
  }
  return out;
}

/** Flat grey buffer (degenerate-grip + not-yet-implemented modes). */
function greyBuffer(n: number): Float32Array {
  const out = new Float32Array(n * 3);
  const g = new THREE.Color(GREY);
  for (let i = 0; i < n; i++) { out[i * 3] = g.r; out[i * 3 + 1] = g.g; out[i * 3 + 2] = g.b; }
  return out;
}

/** Degenerate-grip test, shared with TrackSurfacePanel (which calls it on
 *  surface.mesh_tri_grip to disable the GRIP control + pick the default
 *  mode). Grip is "available" only when the per-vertex μ has real spread:
 *  range > 0.02 and not effectively all-0 or all-1. Empty/absent → false
 *  (also the no-gt / provisional case, where there is no per-vertex grip). */
export function isGripAvailable(grip: readonly number[] | null | undefined): boolean {
  if (!grip || grip.length === 0) return false;
  let mn = Infinity; let mx = -Infinity;
  for (const g of grip) { if (g < mn) mn = g; if (g > mx) mx = g; }
  return (mx - mn > 0.02) && !(mx <= 0.02) && !(mn >= 0.98);
}

/** [min,max] over finite values (EXEC-7 SPEED domain). Safe fallback for
 *  empty / single-value inputs so makeColorBuffer's domain span is never 0. */
function finiteDomain(vals: ArrayLike<number | null | undefined>): [number, number] {
  let mn = Infinity; let mx = -Infinity;
  for (let i = 0; i < vals.length; i++) {
    const v = vals[i];
    if (v != null && Number.isFinite(v)) { if (v < mn) mn = v; if (v > mx) mx = v; }
  }
  if (!Number.isFinite(mn) || !Number.isFinite(mx) || mn === mx) return [0, 1];
  return [mn, mx];
}

/** Mean of bin.elevation_m (finite values only). Used to mean-subtract
 *  z = (elev - mean) × ELEVATION_SCALE so the rendered surface is
 *  centred at z = 0 regardless of AMSL altitude. Without this, OK
 *  (Essay plateau ~178 m) renders 270 m above the auto-fit camera
 *  target (0, 0, 0) and is invisible — only sea-level tracks happen
 *  to render in-frustum. Returns 0 if bins is empty / all elevations
 *  are non-finite (defensive — keeps mesh at origin instead of NaN). */
function meanElevationFromBins(bins: SurfaceBin[]): number {
  let sum = 0;
  let n = 0;
  for (const b of bins) {
    const e = b.elevation_m;
    if (typeof e === 'number' && Number.isFinite(e)) {
      sum += e;
      n++;
    }
  }
  return n > 0 ? sum / n : 0;
}

/* ── EXEC-6: longitudinal gradient profile ────────────────
 * Per-bin slope g(s) = d(elevation_m)/d(distance_m) via central differences
 * over bins sorted by arclength. RAW elevation (the 2× z exaggeration is
 * geometry-only). G = max(|g|) with a 0.05 (5 %) floor so a dead-flat track
 * doesn't normalise sensor noise into a saturated rainbow. Exported so the
 * panel legend can label the symmetric ±G domain as a percentage. */
export function gradientProfile(
  bins: SurfaceBin[],
): { sSorted: number[]; gPerBin: number[]; G: number } {
  const usable = bins.filter(
    (b) => Number.isFinite(b.elevation_m) && Number.isFinite(b.distance_m),
  );
  const sorted = usable.slice().sort((a, b) => a.distance_m - b.distance_m);
  const nB = sorted.length;
  const sSorted = sorted.map((b) => b.distance_m);
  const e = sorted.map((b) => b.elevation_m);
  const gPerBin = new Array<number>(nB).fill(0);
  if (nB >= 2) {
    for (let i = 0; i < nB; i++) {
      const lo = Math.max(0, i - 1);
      const hi = Math.min(nB - 1, i + 1);
      const ds = sSorted[hi]! - sSorted[lo]!;
      gPerBin[i] = ds > 1e-9 ? (e[hi]! - e[lo]!) / ds : 0;
    }
  }
  let G = 0;
  for (const v of gPerBin) { const a = Math.abs(v); if (a > G) G = a; }
  G = Math.max(G, 0.05);
  return { sSorted, gPerBin, G };
}

/** Per-vertex GRADIENT colour buffer (EXEC-6). Samples the 1D gradient
 *  profile at each vertex's arclength s (binary-search + linear interp,
 *  mirroring the elevation interp in buildTriangulatedSurface), then maps
 *  over the symmetric [-G, +G] domain with the blue→grey→red ramp. */
function buildGradientBuffer(
  meshTriSn: [number, number][],
  bins: SurfaceBin[],
): Float32Array {
  const { sSorted, gPerBin, G } = gradientProfile(bins);
  const nB = sSorted.length;
  const V = meshTriSn.length;
  const scalars = new Array<number>(V);
  for (let i = 0; i < V; i++) {
    const s = meshTriSn[i]![0];
    if (nB < 2) { scalars[i] = 0; continue; }
    const sClamped = Math.max(sSorted[0]!, Math.min(sSorted[nB - 1]!, s));
    let lo = 0; let hi = nB - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (sSorted[mid]! <= sClamped) lo = mid; else hi = mid;
    }
    const span = sSorted[hi]! - sSorted[lo]!;
    const u = span > 1e-9 ? (sClamped - sSorted[lo]!) / span : 0;
    scalars[i] = gPerBin[lo]! + u * (gPerBin[hi]! - gPerBin[lo]!);
  }
  return makeColorBuffer(scalars, GRADIENT_STOPS, [-G, G]);
}

/* ── Types ────────────────────────────────────────────── */

// EXEC-4/5: 'speed' + 'gradient' are the new V1 modes; the legacy
// 'elevation'/'line-delta'/'spatial-grip' remain in the union until
// EXEC-5 removes their panel buttons. The buffer-swap colour system
// only populates grip/speed/gradient; legacy modes fall back to grip.
export type HeatmapMode = 'grip' | 'speed' | 'gradient' | 'elevation' | 'line-delta' | 'spatial-grip';

export interface TrackSurface3DProps {
  sessionId: string;
  /** Selected A-lap (lap_number). Threaded into useTrackSurfaceData so the
   *  surface + gps-trace fetches request this lap (?lap=N) — drives SPEED
   *  colouring (EXEC-7) and the driven-line overlay (EXEC-8). null/undefined
   *  = server default (best lap). */
  lap?: number | null;
  mode?: HeatmapMode;
  /** When `mode === 'spatial-grip'`, choose which factor to isolate.
   *  Defaults to 'combined' (effective μ). Ignored in other modes. */
  spatialFactor?: SpatialFactor;
  showOptimalLine?: boolean;
  showActualLine?: boolean;
  className?: string;
}

/* ── Helpers: project GPS to local XY ─────────────────── */

interface XYPoint { x: number; y: number }

function gpsToLocalXY(
  latitudes: number[],
  longitudes: number[],
): XYPoint[] {
  if (latitudes.length === 0) return [];
  let sumLat = 0;
  let sumLon = 0;
  for (let i = 0; i < latitudes.length; i++) {
    sumLat += latitudes[i]!;
    sumLon += longitudes[i]!;
  }
  const meanLat = sumLat / latitudes.length;
  const meanLon = sumLon / latitudes.length;
  const latScale = 111320; // metres per degree latitude
  const lonScale = 111320 * Math.cos((meanLat * Math.PI) / 180);

  return latitudes.map((lat, i) => ({
    x: (longitudes[i]! - meanLon) * lonScale,
    y: (lat - meanLat) * latScale,
  }));
}

/* ── Build centerline from GPS or fallback straight ───── */

interface CenterlinePoint {
  x: number;
  y: number;
  distance: number;
}

function buildCenterline(
  bins: SurfaceBin[],
  gpsXY: XYPoint[] | null,
  gpsDistances: number[] | null,
): CenterlinePoint[] {
  if (gpsXY && gpsDistances && gpsXY.length >= 2 && gpsDistances.length === gpsXY.length) {
    // Resample GPS points to match bin distances via linear interpolation
    const result: CenterlinePoint[] = [];
    let gpsIdx = 0;
    for (const bin of bins) {
      const d = bin.distance_m;
      while (gpsIdx < gpsDistances.length - 2 && gpsDistances[gpsIdx + 1]! < d) {
        gpsIdx++;
      }
      const d0 = gpsDistances[gpsIdx]!;
      const d1 = gpsDistances[Math.min(gpsIdx + 1, gpsDistances.length - 1)]!;
      const span = d1 - d0;
      const t = span > 0.001 ? Math.max(0, Math.min(1, (d - d0) / span)) : 0;
      const p0 = gpsXY[gpsIdx]!;
      const p1 = gpsXY[Math.min(gpsIdx + 1, gpsXY.length - 1)]!;
      result.push({
        x: p0.x + (p1.x - p0.x) * t,
        y: p0.y + (p1.y - p0.y) * t,
        distance: d,
      });
    }
    return result;
  }

  // Fallback: straight ribbon along X axis
  return bins.map((bin) => ({
    x: bin.distance_m,
    y: 0,
    distance: bin.distance_m,
  }));
}

/* ── Build heatmap value [0..1] for each bin ──────────── */

function binHeatValues(
  bins: SurfaceBin[],
  mode: HeatmapMode,
  lineDelta: LineDeltaPoint[] | null,
  conditions: WeatherConditionBlock | null | undefined,
  spatialFactor: SpatialFactor = 'combined',
): number[] {
  if (mode === 'grip') {
    let minMu = Infinity;
    let maxMu = -Infinity;
    for (const b of bins) { minMu = Math.min(minMu, b.mu_lat_p95); maxMu = Math.max(maxMu, b.mu_lat_p95); }
    const range = maxMu - minMu || 1;
    return bins.map((b) => (b.mu_lat_p95 - minMu) / range);
  }

  if (mode === 'gradient') {
    // Fallback-ribbon GRADIENT colouring (the gt Delaunay path uses the
    // 3-stop buffer instead). Reuse gradientProfile, sample each bin's slope,
    // map [-G,+G] → [0,1] (0.5 = flat). Both edge vertices share the value.
    const { sSorted, gPerBin, G } = gradientProfile(bins);
    const nB = sSorted.length;
    if (nB < 2) return bins.map(() => 0.5);
    const sampleAtS = (s: number): number => {
      const sC = Math.max(sSorted[0]!, Math.min(sSorted[nB - 1]!, s));
      let lo = 0; let hi = nB - 1;
      while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (sSorted[mid]! <= sC) lo = mid; else hi = mid; }
      const span = sSorted[hi]! - sSorted[lo]!;
      const u = span > 1e-9 ? (sC - sSorted[lo]!) / span : 0;
      return gPerBin[lo]! + u * (gPerBin[hi]! - gPerBin[lo]!);
    };
    return bins.map((b) => Math.max(0, Math.min(1, 0.5 + sampleAtS(b.distance_m) / (2 * G))));
  }

  if (mode === 'elevation') {
    let minE = Infinity;
    let maxE = -Infinity;
    for (const b of bins) { minE = Math.min(minE, b.elevation_m); maxE = Math.max(maxE, b.elevation_m); }
    const range = maxE - minE || 1;
    return bins.map((b) => (b.elevation_m - minE) / range);
  }

  if (mode === 'spatial-grip') {
    // Day-13 Phase D/E: render the Day-12 spatial μ modifier on the mesh.
    // Combined (default): effective_mu(s) = mu_data × mu_scale × factor_values(s).
    // Iso-factor: render one of drainage/sun/wind components on its own,
    // normalized to [0.85, 1.30] with the higher factor (= wetter) rendered
    // red and the lower factor (= drier baseline) rendered green. Same
    // green=more-grip semantic across all four sub-modes.
    //
    // Spatial arrays are aligned to spatial_modifier.arclength_samples (length
    // N_s = Frenet segments), NOT to bins[].distance_m. We resample by walking
    // samples in lockstep with bin distances (nearest-neighbor; sufficient at
    // typical 1-2 m bin / 5 m segment density). Falls back to plain min/max
    // grip when spatial data is absent — the panel disables the mode button
    // upstream so we shouldn't normally reach this branch.
    const sm = conditions?.spatial_modifier;
    if (!conditions || !sm || sm.arclength_samples.length < 2) {
      let minMu = Infinity;
      let maxMu = -Infinity;
      for (const b of bins) { minMu = Math.min(minMu, b.mu_lat_p95); maxMu = Math.max(maxMu, b.mu_lat_p95); }
      const range = maxMu - minMu || 1;
      return bins.map((b) => (b.mu_lat_p95 - minMu) / range);
    }

    const samples = sm.arclength_samples;
    const isCombined = spatialFactor === 'combined';

    // Pick which array to sample + the color range to normalize across.
    const factorArr: readonly number[] =
      spatialFactor === 'drainage' ? sm.drainage_components
      : spatialFactor === 'sun' ? sm.sun_components
      : spatialFactor === 'wind' ? sm.wind_components
      : sm.factor_values;
    const colorMin = isCombined ? SPATIAL_GRIP_COLOR_MIN : INDIVIDUAL_FACTOR_MIN;
    const colorMax = isCombined ? SPATIAL_GRIP_COLOR_MAX : INDIVIDUAL_FACTOR_MAX;

    const muScale = conditions.mu_scale;
    let smIdx = 0;
    return bins.map((b) => {
      while (smIdx < samples.length - 2 && samples[smIdx + 1]! < b.distance_m) {
        smIdx++;
      }
      const raw = factorArr[smIdx] ?? 1.0;
      // Combined: convert producer factor_values into effective_mu before
      // normalizing. Iso-factor: use the raw component verbatim, then
      // invert (high factor → wetter → red).
      const value = isCombined ? b.mu_lat_p95 * muScale * raw : raw;
      let t = (value - colorMin) / (colorMax - colorMin);
      t = Math.max(0, Math.min(1, t));
      return isCombined ? t : 1 - t;
    });
  }

  // line-delta: build lookup by distance, fallback to 0.5
  if (lineDelta && lineDelta.length > 0) {
    let maxDelta = 0;
    for (const p of lineDelta) { maxDelta = Math.max(maxDelta, Math.abs(p.delta_m)); }
    const scale = maxDelta || 1;
    // Index delta points by distance for fast lookup
    let dIdx = 0;
    return bins.map((b) => {
      while (dIdx < lineDelta.length - 2 && lineDelta[dIdx + 1]!.distance_m < b.distance_m) {
        dIdx++;
      }
      const closest = lineDelta[dIdx]!;
      const normDelta = Math.min(Math.abs(closest.delta_m) / scale, 1);
      return 1 - normDelta; // 1 = on-line (green), 0 = off-line (red)
    });
  }

  return bins.map(() => 0.5);
}

/* ── Day-13 Phase D — per-edge 2D field sampling ──────── */

/** Sample the per-tile 2D field at the LEFT and RIGHT edge of each
 *  bin's cross-section. The renderer then assigns different colors to
 *  the two edge vertices → cross-track gradients become visible on the
 *  3D ribbon (e.g., inside-pools / outside-drains on banked sections).
 *
 *  Returns ``null`` when 2D fields aren't available — the renderer
 *  falls back to longitudinal-only coloring via the 1D per-bin
 *  heatValues. */
function binEdgeHeatValuesFromField2D(
  bins: SurfaceBin[],
  conditions: WeatherConditionBlock | null | undefined,
  spatialFactor: SpatialFactor,
): { left: number[]; right: number[] } | null {
  const sm = conditions?.spatial_modifier;
  if (!sm) return null;
  const field =
    spatialFactor === 'drainage' ? sm.drainage_field_2d
    : spatialFactor === 'sun' ? sm.sun_field_2d
    : spatialFactor === 'wind' ? sm.wind_field_2d
    : sm.factor_field_2d;
  const shape = sm.tile_grid_shape;
  const tileS = sm.tile_arclength_samples;
  const tileN = sm.tile_lateral_offsets;
  if (!field || !shape || !tileS || !tileN) return null;
  const [M_s, M_n] = shape;
  if (M_s < 1 || M_n < 1) return null;

  const isCombined = spatialFactor === 'combined';
  const colorMin = isCombined ? SPATIAL_GRIP_COLOR_MIN : INDIVIDUAL_FACTOR_MIN;
  const colorMax = isCombined ? SPATIAL_GRIP_COLOR_MAX : INDIVIDUAL_FACTOR_MAX;
  const muScale = conditions.mu_scale;

  // Nearest-neighbor sampling. tileS is monotonic; cache si across bins
  // (bins[].distance_m is also monotonic in lap order so the walk
  // amortizes to O(M_s + bins.length)).
  let siCache = 0;
  function sample(sQ: number, nQ: number): number {
    while (siCache < M_s - 1 && (tileS![siCache + 1] ?? Infinity) < sQ) siCache++;
    let ni = 0;
    while (ni < M_n - 1 && (tileN![ni + 1] ?? Infinity) < nQ) ni++;
    return field![siCache * M_n + ni] ?? 1.0;
  }

  const left: number[] = new Array(bins.length);
  const right: number[] = new Array(bins.length);
  for (let i = 0; i < bins.length; i++) {
    const bin = bins[i]!;
    const legacyHalf = bin.width_m != null ? bin.width_m / 2 : null;
    const wLeft = bin.width_left_m ?? legacyHalf ?? DEFAULT_WIDTH_LEFT;
    const wRight = bin.width_right_m ?? legacyHalf ?? DEFAULT_WIDTH_RIGHT;
    // Convention: +n = LEFT of centerline (matches FrenetFrame). The
    // LEFT vertex lives at n = +wLeft, the RIGHT vertex at n = -wRight.
    const rawL = sample(bin.distance_m, wLeft);
    const rawR = sample(bin.distance_m, -wRight);
    // Combined view converts the producer factor into effective_mu
    // before normalizing; iso-factor uses the raw component verbatim.
    const valL = isCombined ? bin.mu_lat_p95 * muScale * rawL : rawL;
    const valR = isCombined ? bin.mu_lat_p95 * muScale * rawR : rawR;
    let tL = Math.max(0, Math.min(1, (valL - colorMin) / (colorMax - colorMin)));
    let tR = Math.max(0, Math.min(1, (valR - colorMin) / (colorMax - colorMin)));
    if (!isCombined) { tL = 1 - tL; tR = 1 - tR; }
    left[i] = tL;
    right[i] = tR;
  }
  return { left, right };
}

/* ── Ribbon mesh geometry builder ─────────────────────── */

/* ── Constrained Delaunay triangulated surface (PRIMARY render) ─── */

/** Indexed BufferGeometry from per-vertex xy + per-triangle indices +
 *  per-vertex grip (already combined 2D/1D-fallback on the producer side).
 *  Replaces the M×K structured grid for the actual render — the M×K stays
 *  available as a dispatcher fallback and is still the logical coordinate
 *  system for the optimiser + grip cache key. Per-vertex elevation is
 *  picked up from ``bins`` by nearest s. */
function buildTriangulatedSurface(
  triXy: [number, number][],
  triIndices: [number, number, number][],
  triSn: [number, number][],
  bins: SurfaceBin[],
): THREE.BufferGeometry {
  const V = triXy.length;
  const T = triIndices.length;
  if (V === 0 || T === 0) return new THREE.BufferGeometry();

  const positions = new Float32Array(V * 3);
  // EXEC-4: colour is no longer baked here — it is mode-driven via
  // colorBuffers + a swap effect in Scene. We seed a flat grey
  // placeholder so MeshLambertMaterial (vertexColors:true) has a valid
  // colour attribute on first paint before the swap effect runs.
  const colors = new Float32Array(V * 3).fill(0.4);
  const indices = new Uint32Array(T * 3);

  // Elevation by s: sort bins once, binary-search per vertex.
  // Mean-subtract elev so z is centred at 0 (otherwise tracks on plateaus
  // like Essay @ ~178m AMSL render way above the auto-fit camera target).
  const meanElev = meanElevationFromBins(bins);
  const sortedBins = bins.slice().sort((a, b) => a.distance_m - b.distance_m);
  const sArr = sortedBins.map((b) => b.distance_m);
  const eArr = sortedBins.map((b) => b.elevation_m ?? meanElev);
  const sMax = sArr.length > 0 ? sArr[sArr.length - 1]! : 0;

  for (let i = 0; i < V; i++) {
    const [x, y] = triXy[i]!;
    const [s] = triSn[i]!;
    // Linear interp of elevation by s; clamp to [0, sMax].
    let elev = 0;
    if (sArr.length >= 2) {
      const sClamped = Math.max(0, Math.min(sMax, s));
      // Binary search for the s bracket.
      let lo = 0;
      let hi = sArr.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (sArr[mid]! <= sClamped) lo = mid; else hi = mid;
      }
      const span = sArr[hi]! - sArr[lo]!;
      const u = span > 1e-9 ? (sClamped - sArr[lo]!) / span : 0;
      const elevAbs = eArr[lo]! + u * (eArr[hi]! - eArr[lo]!);
      elev = (elevAbs - meanElev) * ELEVATION_SCALE;
    }
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = elev;
  }

  for (let t = 0; t < T; t++) {
    const [a, b, c] = triIndices[t]!;
    indices[t * 3] = a;
    indices[t * 3 + 1] = b;
    indices[t * 3 + 2] = c;
  }

  const geo = new THREE.BufferGeometry();
  geo.setIndex(new THREE.BufferAttribute(indices, 1));
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  // EXEC-3: smooth (averaged) vertex normals so adjacent triangles
  // shade as one continuous lit membrane under Lambert, not hard-edged
  // flat patches. boundingBox feeds the EXEC-2 fit-to-bbox camera.
  geo.computeVertexNormals();
  geo.computeBoundingBox();
  geo.computeBoundingSphere();
  return geo;
}


function buildSurfaceGeometry(
  centerline: CenterlinePoint[],
  bins: SurfaceBin[],
  heatValues: number[],
  mode: HeatmapMode,
  edgeValues: { left: number[]; right: number[] } | null = null,
): THREE.BufferGeometry {
  const count = centerline.length;
  if (count < 2) return new THREE.BufferGeometry();

  const vertCount = count * 2;
  const triCount = (count - 1) * 2;
  const positions = new Float32Array(vertCount * 3);
  const colors = new Float32Array(vertCount * 3);
  const indices = new Uint32Array(triCount * 3);

  const palette = COLORS[mode];
  const colHigh = new THREE.Color(palette.high);
  const colLow = new THREE.Color(palette.low);
  const tmpColor = new THREE.Color();
  const meanElev = meanElevationFromBins(bins);

  for (let i = 0; i < count; i++) {
    const pt = centerline[i]!;
    const bin = bins[i]!;
    // Asymmetric width: prefer per-side fields, fall back to half of legacy
    // width_m, then to DEFAULT_WIDTH_* (4 m + 4 m).
    const legacyHalf = bin.width_m != null ? bin.width_m / 2 : null;
    const wLeft = bin.width_left_m ?? legacyHalf ?? DEFAULT_WIDTH_LEFT;
    const wRight = bin.width_right_m ?? legacyHalf ?? DEFAULT_WIDTH_RIGHT;
    const elev = (bin.elevation_m - meanElev) * ELEVATION_SCALE;

    // Compute perpendicular direction from tangent
    let tx: number;
    let ty: number;
    if (i < count - 1) {
      tx = centerline[i + 1]!.x - pt.x;
      ty = centerline[i + 1]!.y - pt.y;
    } else {
      tx = pt.x - centerline[i - 1]!.x;
      ty = pt.y - centerline[i - 1]!.y;
    }
    const tLen = Math.sqrt(tx * tx + ty * ty) || 1;
    // (nx, ny) is the LEFT normal: +90° CCW rotation of the tangent.
    // → pt + (nx,ny)*w lies w metres to the LEFT of the centerline,
    //   pt - (nx,ny)*w lies w metres to the RIGHT.
    const nx = -ty / tLen;
    const ny = tx / tLen;

    const li = i * 2;       // buffer slot at the RIGHT-side vertex (pt - n*wRight)
    const ri = i * 2 + 1;   // buffer slot at the LEFT-side vertex (pt + n*wLeft)

    positions[li * 3] = pt.x - nx * wRight;
    positions[li * 3 + 1] = pt.y - ny * wRight;
    positions[li * 3 + 2] = elev;
    positions[ri * 3] = pt.x + nx * wLeft;
    positions[ri * 3 + 1] = pt.y + ny * wLeft;
    positions[ri * 3 + 2] = elev;

    // Vertex colors — per-edge when 2D fields are sampled (Day-13
    // Phase D), single per-bin otherwise. li is the RIGHT physical
    // vertex; ri is the LEFT physical vertex (see comment above).
    if (edgeValues) {
      const tLeft = edgeValues.left[i] ?? 0.5;
      const tRight = edgeValues.right[i] ?? 0.5;
      tmpColor.copy(colLow).lerp(colHigh, tRight);
      colors[li * 3] = tmpColor.r;
      colors[li * 3 + 1] = tmpColor.g;
      colors[li * 3 + 2] = tmpColor.b;
      tmpColor.copy(colLow).lerp(colHigh, tLeft);
      colors[ri * 3] = tmpColor.r;
      colors[ri * 3 + 1] = tmpColor.g;
      colors[ri * 3 + 2] = tmpColor.b;
    } else {
      const t = heatValues[i] ?? 0.5;
      tmpColor.copy(colLow).lerp(colHigh, t);
      colors[li * 3] = tmpColor.r;
      colors[li * 3 + 1] = tmpColor.g;
      colors[li * 3 + 2] = tmpColor.b;
      colors[ri * 3] = tmpColor.r;
      colors[ri * 3 + 1] = tmpColor.g;
      colors[ri * 3 + 2] = tmpColor.b;
    }
  }

  for (let i = 0; i < count - 1; i++) {
    const bl = i * 2;
    const br = i * 2 + 1;
    const tl = (i + 1) * 2;
    const tr = (i + 1) * 2 + 1;
    const ti = i * 6;
    indices[ti] = bl;
    indices[ti + 1] = br;
    indices[ti + 2] = tl;
    indices[ti + 3] = br;
    indices[ti + 4] = tr;
    indices[ti + 5] = tl;
  }

  const geo = new THREE.BufferGeometry();
  geo.setIndex(new THREE.BufferAttribute(indices, 1));
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.computeVertexNormals();
  geo.computeBoundingBox();
  geo.computeBoundingSphere();
  return geo;
}

/* ── Path F literal-edge mesh geometry builder ────────── */

/** Resample a closed polyline to ``n`` points at uniform arclength.
 *  Matches the Python ``_resample_polyline_arclength`` convention. */
function resamplePolylineArclength(
  xy: [number, number][],
  n: number,
): [number, number][] {
  if (xy.length < 2) return xy.length === 1 ? Array(n).fill(xy[0]!) : [];
  const cum: number[] = [0];
  for (let i = 1; i < xy.length; i++) {
    const dx = xy[i]![0] - xy[i - 1]![0];
    const dy = xy[i]![1] - xy[i - 1]![1];
    cum.push(cum[i - 1]! + Math.sqrt(dx * dx + dy * dy));
  }
  const total = cum[cum.length - 1]!;
  if (total <= 0) return Array(n).fill(xy[0]!);
  const out: [number, number][] = new Array(n);
  let j = 0;
  for (let i = 0; i < n; i++) {
    const t = (i / n) * total;
    while (j < cum.length - 2 && cum[j + 1]! < t) j++;
    const span = cum[j + 1]! - cum[j]!;
    const u = span > 1e-9 ? (t - cum[j]!) / span : 0;
    out[i] = [
      xy[j]![0] + u * (xy[j + 1]![0] - xy[j]![0]),
      xy[j]![1] + u * (xy[j + 1]![1] - xy[j]![1]),
    ];
  }
  return out;
}

/** Build a triangulated ribbon mesh BETWEEN two hand-traced edge polylines.
 *  Shape == hand-tracing by construction (mesh boundary lies on the
 *  resampled polyline within numerical precision). Path F architecture
 *  fix for the gate failure under Path E spine±width rendering. */
function buildLiteralEdgeMesh(
  leftEdgeRaw: [number, number][],
  rightEdgeRaw: [number, number][],
  leftEdgeSn: [number, number][] | null | undefined,
  rightEdgeSn: [number, number][] | null | undefined,
  bins: SurfaceBin[],
  heatValues: number[],
  mode: HeatmapMode,
  conditions: WeatherConditionBlock | null | undefined,
  spatialFactor: SpatialFactor,
  midlineLength: number,
): THREE.BufferGeometry {
  // n_stations = max(300, midline_length / 1.5) per the staging spec.
  const nStations = Math.max(300, Math.floor(midlineLength / 1.5));
  const left = resamplePolylineArclength(leftEdgeRaw, nStations);
  const right = resamplePolylineArclength(rightEdgeRaw, nStations);
  if (left.length < 2 || right.length < 2) return new THREE.BufferGeometry();

  // Resample the per-vertex (s, n) arrays to nStations the same way so
  // each mesh vertex retains its (s, n) coordinate. We can resample by
  // arclength on the ORIGINAL edge polyline since the s/n values are
  // attached 1:1 to the original points.
  const leftSnResampled = leftEdgeSn
    ? resamplePolylineArclength(leftEdgeSn as [number, number][], nStations)
    : null;
  const rightSnResampled = rightEdgeSn
    ? resamplePolylineArclength(rightEdgeSn as [number, number][], nStations)
    : null;

  const vertCount = nStations * 2;
  const positions = new Float32Array(vertCount * 3);
  const colors = new Float32Array(vertCount * 3);

  const palette = COLORS[mode];
  const colHigh = new THREE.Color(palette.high);
  const colLow = new THREE.Color(palette.low);
  const tmpColor = new THREE.Color();

  // Per-vertex elevation from nearest bin by arclength s (when available).
  // Mean-subtracted so plateau tracks (Essay @ ~178m AMSL) don't render
  // off-frustum. meanElevLE is named so the inner-loop substitution is
  // unambiguous; same value as meanElevationFromBins(bins).
  const meanElevLE = meanElevationFromBins(bins);
  const binsByDist = bins;
  const binDistances = bins.map((b) => b.distance_m);
  const nearestBinIdx = (sVal: number): number => {
    if (binsByDist.length === 0) return 0;
    let lo = 0;
    let hi = binDistances.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (binDistances[mid]! < sVal) lo = mid + 1; else hi = mid;
    }
    return Math.max(0, Math.min(binDistances.length - 1, lo));
  };

  // 2D-field sampling helper — mirrors binEdgeHeatValuesFromField2D but
  // takes an explicit (s, n) directly (no width-derived n). Used when
  // mode === 'spatial-grip' AND we have per-vertex (s, n) AND the 2D
  // fields are present.
  const sm = conditions?.spatial_modifier;
  const tileShape = sm?.tile_grid_shape ?? null;
  const tileS = sm?.tile_arclength_samples ?? null;
  const tileN = sm?.tile_lateral_offsets ?? null;
  const fieldArr =
    mode === 'spatial-grip'
      ? (spatialFactor === 'drainage' ? sm?.drainage_field_2d
        : spatialFactor === 'sun' ? sm?.sun_field_2d
        : spatialFactor === 'wind' ? sm?.wind_field_2d
        : sm?.factor_field_2d)
      : null;
  const isCombined = spatialFactor === 'combined';
  const colorMin = isCombined ? SPATIAL_GRIP_COLOR_MIN : INDIVIDUAL_FACTOR_MIN;
  const colorMax = isCombined ? SPATIAL_GRIP_COLOR_MAX : INDIVIDUAL_FACTOR_MAX;
  const muScale = conditions?.mu_scale ?? 1.0;
  const useField2D =
    mode === 'spatial-grip'
    && fieldArr != null && tileShape != null && tileS != null && tileN != null
    && leftSnResampled != null && rightSnResampled != null;

  function sampleField2D(sVal: number, nVal: number): number {
    if (!useField2D) return 1.0;
    const [M_s, M_n] = tileShape!;
    let si = 0;
    while (si < M_s - 1 && (tileS![si + 1] ?? Infinity) < sVal) si++;
    let ni = 0;
    while (ni < M_n - 1 && (tileN![ni + 1] ?? Infinity) < nVal) ni++;
    return (fieldArr as readonly number[])[si * M_n + ni] ?? 1.0;
  }

  for (let i = 0; i < nStations; i++) {
    // Pick (s, n) per vertex; default to mid-distance fallback when absent.
    const sL = leftSnResampled?.[i]?.[0] ?? (i / nStations) * midlineLength;
    const nL = leftSnResampled?.[i]?.[1] ?? 0;
    const sR = rightSnResampled?.[i]?.[0] ?? (i / nStations) * midlineLength;
    const nR = rightSnResampled?.[i]?.[1] ?? 0;

    // Elevation per vertex from nearest spine bin, mean-subtracted.
    const elevLBin = binsByDist[nearestBinIdx(sL)];
    const elevRBin = binsByDist[nearestBinIdx(sR)];
    const elevL = ((elevLBin?.elevation_m ?? meanElevLE) - meanElevLE) * ELEVATION_SCALE;
    const elevR = ((elevRBin?.elevation_m ?? meanElevLE) - meanElevLE) * ELEVATION_SCALE;

    // li = LEFT physical vertex; ri = RIGHT physical vertex.
    const li = i * 2;
    const ri = i * 2 + 1;
    positions[li * 3] = left[i]![0];
    positions[li * 3 + 1] = left[i]![1];
    positions[li * 3 + 2] = elevL;
    positions[ri * 3] = right[i]![0];
    positions[ri * 3 + 1] = right[i]![1];
    positions[ri * 3 + 2] = elevR;

    // Color: per-vertex via 2D field when present, else per-spine-bin scalar.
    let tL: number;
    let tR: number;
    if (useField2D) {
      const rawL = sampleField2D(sL, nL);
      const rawR = sampleField2D(sR, nR);
      const muL = binsByDist[nearestBinIdx(sL)]?.mu_lat_p95 ?? 0;
      const muR = binsByDist[nearestBinIdx(sR)]?.mu_lat_p95 ?? 0;
      const valL = isCombined ? muL * muScale * rawL : rawL;
      const valR = isCombined ? muR * muScale * rawR : rawR;
      tL = Math.max(0, Math.min(1, (valL - colorMin) / (colorMax - colorMin)));
      tR = Math.max(0, Math.min(1, (valR - colorMin) / (colorMax - colorMin)));
      if (!isCombined) { tL = 1 - tL; tR = 1 - tR; }
    } else {
      // Use the per-bin scalar heatValues — both edge vertices get the
      // same colour for a station (gradient across the cross-section
      // requires 2D field data).
      const iL = nearestBinIdx(sL);
      const iR = nearestBinIdx(sR);
      tL = heatValues[iL] ?? 0.5;
      tR = heatValues[iR] ?? 0.5;
    }
    tmpColor.copy(colLow).lerp(colHigh, tL);
    colors[li * 3] = tmpColor.r;
    colors[li * 3 + 1] = tmpColor.g;
    colors[li * 3 + 2] = tmpColor.b;
    tmpColor.copy(colLow).lerp(colHigh, tR);
    colors[ri * 3] = tmpColor.r;
    colors[ri * 3 + 1] = tmpColor.g;
    colors[ri * 3 + 2] = tmpColor.b;
  }

  // Closed-loop triangulation: each station i pairs to (i+1) % n; last
  // quad wraps i+1 → 0 so the mesh closes at the start/finish seam.
  const triCount = nStations * 2;
  const indices = new Uint32Array(triCount * 3);
  for (let i = 0; i < nStations; i++) {
    const iNext = (i + 1) % nStations;
    const li = i * 2;
    const ri = i * 2 + 1;
    const liN = iNext * 2;
    const riN = iNext * 2 + 1;
    const ti = i * 6;
    indices[ti] = li;
    indices[ti + 1] = ri;
    indices[ti + 2] = liN;
    indices[ti + 3] = ri;
    indices[ti + 4] = riN;
    indices[ti + 5] = liN;
  }

  const geo = new THREE.BufferGeometry();
  geo.setIndex(new THREE.BufferAttribute(indices, 1));
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.computeVertexNormals();
  geo.computeBoundingBox();
  geo.computeBoundingSphere();
  return geo;
}

/* ── Stage 1 M×K mesh from medial-axis spine ─────────────── */

/** Triangulate the M×K grid as (M)×(K-1)×2 triangles. Each "cell" is one
 *  longitudinal step × one lateral step on the grid. Closed-loop wrap
 *  on M handled by connecting station M-1 to station 0. */
function buildMxKMesh(
  spineXy: [number, number][],
  L_xy: [number, number][],
  R_xy: [number, number][],
  spineS: number[],
  hwL: number[],
  hwR: number[],
  K: number,
  bins: SurfaceBin[],
  mode: HeatmapMode,
  conditions: WeatherConditionBlock | null | undefined,
  spatialFactor: SpatialFactor,
): THREE.BufferGeometry {
  const M = spineXy.length;
  if (M < 2 || L_xy.length !== M || R_xy.length !== M || K < 2) {
    return new THREE.BufferGeometry();
  }

  // Per-vertex positions: M × K = 7200 for KCT (300×24).
  const vertCount = M * K;
  const positions = new Float32Array(vertCount * 3);
  const colors = new Float32Array(vertCount * 3);

  // Per-vertex elevation from nearest spine-bin via s.
  const binDistances = bins.map((b) => b.distance_m);
  const nearestBinIdx = (sVal: number): number => {
    if (binDistances.length === 0) return 0;
    let lo = 0;
    let hi = binDistances.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (binDistances[mid]! < sVal) lo = mid + 1; else hi = mid;
    }
    return Math.max(0, Math.min(binDistances.length - 1, lo));
  };

  // 2D-field sampler for spatial-grip mode.
  const sm = conditions?.spatial_modifier;
  const tileShape = sm?.tile_grid_shape ?? null;
  const tileS = sm?.tile_arclength_samples ?? null;
  const tileN = sm?.tile_lateral_offsets ?? null;
  const fieldArr =
    mode === 'spatial-grip'
      ? (spatialFactor === 'drainage' ? sm?.drainage_field_2d
        : spatialFactor === 'sun' ? sm?.sun_field_2d
        : spatialFactor === 'wind' ? sm?.wind_field_2d
        : sm?.factor_field_2d)
      : null;
  const useField2D =
    mode === 'spatial-grip'
    && fieldArr != null && tileShape != null && tileS != null && tileN != null;
  const isCombined = spatialFactor === 'combined';
  const colorMin = isCombined ? SPATIAL_GRIP_COLOR_MIN : INDIVIDUAL_FACTOR_MIN;
  const colorMax = isCombined ? SPATIAL_GRIP_COLOR_MAX : INDIVIDUAL_FACTOR_MAX;
  const muScale = conditions?.mu_scale ?? 1.0;
  function sampleField2D(sVal: number, nVal: number): number {
    if (!useField2D) return 1.0;
    const [M_s, M_n] = tileShape!;
    let si = 0;
    while (si < M_s - 1 && (tileS![si + 1] ?? Infinity) < sVal) si++;
    let ni = 0;
    while (ni < M_n - 1 && (tileN![ni + 1] ?? Infinity) < nVal) ni++;
    return (fieldArr as readonly number[])[si * M_n + ni] ?? 1.0;
  }

  // Per-bin scalar heatmap (grip / elevation / line-delta).
  let heatMin = Infinity;
  let heatMax = -Infinity;
  if (mode === 'grip') {
    for (const b of bins) { heatMin = Math.min(heatMin, b.mu_lat_p95); heatMax = Math.max(heatMax, b.mu_lat_p95); }
  } else if (mode === 'elevation') {
    for (const b of bins) { heatMin = Math.min(heatMin, b.elevation_m); heatMax = Math.max(heatMax, b.elevation_m); }
  }
  const heatRange = (heatMax - heatMin) || 1;

  const palette = COLORS[mode];
  const colHigh = new THREE.Color(palette.high);
  const colLow = new THREE.Color(palette.low);
  const tmpColor = new THREE.Color();
  const meanElev = meanElevationFromBins(bins);

  for (let i = 0; i < M; i++) {
    const L = L_xy[i]!;
    const R = R_xy[i]!;
    const s = spineS[i] ?? 0;
    const hl = hwL[i] ?? 0;
    const hr = hwR[i] ?? 0;
    const totalW = hl + hr;
    const elevBin = bins[nearestBinIdx(s)];
    const elev = ((elevBin?.elevation_m ?? meanElev) - meanElev) * ELEVATION_SCALE;
    const heat = mode === 'grip'
      ? ((elevBin?.mu_lat_p95 ?? 0) - heatMin) / heatRange
      : mode === 'elevation'
      ? ((elevBin?.elevation_m ?? 0) - heatMin) / heatRange
      : 0.5;
    for (let k = 0; k < K; k++) {
      const t = K > 1 ? k / (K - 1) : 0;
      const x = L[0] + t * (R[0] - L[0]);
      const y = L[1] + t * (R[1] - L[1]);
      const n = hl - t * totalW;  // signed lateral offset (+ = left)
      const idx = i * K + k;
      positions[idx * 3] = x;
      positions[idx * 3 + 1] = y;
      positions[idx * 3 + 2] = elev;
      let colorT: number;
      if (useField2D) {
        const raw = sampleField2D(s, n);
        const muLocal = elevBin?.mu_lat_p95 ?? 0;
        const val = isCombined ? muLocal * muScale * raw : raw;
        let ct = Math.max(0, Math.min(1, (val - colorMin) / (colorMax - colorMin)));
        if (!isCombined) ct = 1 - ct;
        colorT = ct;
      } else {
        colorT = Math.max(0, Math.min(1, heat));
      }
      tmpColor.copy(colLow).lerp(colHigh, colorT);
      colors[idx * 3] = tmpColor.r;
      colors[idx * 3 + 1] = tmpColor.g;
      colors[idx * 3 + 2] = tmpColor.b;
    }
  }

  // Triangulation: M × (K-1) cells, 2 triangles each, cyclic on M.
  const triCount = M * (K - 1) * 2;
  const indices = new Uint32Array(triCount * 3);
  let ti = 0;
  for (let i = 0; i < M; i++) {
    const iNext = (i + 1) % M;
    for (let k = 0; k < K - 1; k++) {
      const a = i * K + k;
      const b = i * K + (k + 1);
      const c = iNext * K + k;
      const d = iNext * K + (k + 1);
      indices[ti++] = a;
      indices[ti++] = b;
      indices[ti++] = c;
      indices[ti++] = b;
      indices[ti++] = d;
      indices[ti++] = c;
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setIndex(new THREE.BufferAttribute(indices, 1));
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.computeVertexNormals();
  geo.computeBoundingBox();
  geo.computeBoundingSphere();
  return geo;
}

/* ── Edge outline tube (Path F: thick black boundary on mesh) ── */

/** Build a closed-loop TubeGeometry along a hand-traced edge polyline.
 *  WebGL line primitives don't render thick lines reliably (most browsers
 *  cap linewidth at 1px), so we use 3D tubes — small radius gives the
 *  visual effect of a thick outline that scales with camera zoom. */
function buildEdgeTubeGeometry(
  edgeXY: [number, number][],
  edgeSn: [number, number][] | null | undefined,
  bins: SurfaceBin[],
  radius: number = 0.25,
  liftZ: number = 0.1,
): THREE.BufferGeometry | null {
  if (edgeXY.length < 2) return null;

  const binDistances = bins.map((b) => b.distance_m);
  const nearestBinIdx = (sVal: number): number => {
    if (binDistances.length === 0) return 0;
    let lo = 0;
    let hi = binDistances.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (binDistances[mid]! < sVal) lo = mid + 1; else hi = mid;
    }
    return Math.max(0, Math.min(binDistances.length - 1, lo));
  };

  const meanElev = meanElevationFromBins(bins);
  const points: THREE.Vector3[] = [];
  for (let i = 0; i < edgeXY.length; i++) {
    const s = edgeSn?.[i]?.[0] ?? 0;
    const absElev = bins[nearestBinIdx(s)]?.elevation_m ?? meanElev;
    const elev = (absElev - meanElev) * ELEVATION_SCALE + liftZ;
    points.push(new THREE.Vector3(edgeXY[i]![0], edgeXY[i]![1], elev));
  }

  // CatmullRom needs ≥ 4 points to interpolate cleanly; below that pad
  // the polyline by duplicating the first point so the tube still
  // generates without throwing.
  while (points.length < 4) points.push(points[0]!.clone());

  const curve = new THREE.CatmullRomCurve3(points, /* closed */ true);
  const tubularSegments = Math.max(64, edgeXY.length * 2);
  return new THREE.TubeGeometry(curve, tubularSegments, radius, 8, true);
}

/* ── Line geometry builder ────────────────────────────── */

function buildLineGeometry(
  centerline: CenterlinePoint[],
  offsets: number[] | null,
  elevationBins: SurfaceBin[],
  liftZ: number,
): THREE.BufferGeometry {
  const meanElev = meanElevationFromBins(elevationBins);
  const pts: number[] = [];
  for (let i = 0; i < centerline.length; i++) {
    const pt = centerline[i]!;
    const offset = offsets?.[i] ?? 0;
    // Apply lateral offset along normal
    let nx = 0;
    let ny = 0;
    if (offset !== 0) {
      let tx: number;
      let ty: number;
      if (i < centerline.length - 1) {
        tx = centerline[i + 1]!.x - pt.x;
        ty = centerline[i + 1]!.y - pt.y;
      } else {
        tx = pt.x - centerline[i - 1]!.x;
        ty = pt.y - centerline[i - 1]!.y;
      }
      const tLen = Math.sqrt(tx * tx + ty * ty) || 1;
      nx = -ty / tLen;
      ny = tx / tLen;
    }
    const absElev = elevationBins[i]?.elevation_m ?? meanElev;
    const elev = (absElev - meanElev) * ELEVATION_SCALE + liftZ;
    pts.push(pt.x + nx * offset, pt.y + ny * offset, elev);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  return geo;
}

/* ── EXEC-8: driven-line positions lifted along the surface normal ──── */

/** Flat [x,y,z, …] positions for the selected lap's driven line, each point
 *  lifted by ε along the estimated surface normal (z-up scene). The normal
 *  is N = T × B with T the 3D centreline tangent and B the horizontal
 *  cross-track direction — so the lift leans with the longitudinal slope
 *  rather than going straight +z (banking is unknown from the centreline,
 *  but the polygonOffset + depthWrite:false handle the rest). Flat track →
 *  N ≈ (0,0,1) → a plain +z lift, as expected. */
function buildDrivenLinePositions(
  centerline: CenterlinePoint[],
  bins: SurfaceBin[],
  eps: number,
): number[] {
  const meanElev = meanElevationFromBins(bins);
  const N = centerline.length;
  const zAt = (i: number) =>
    (((bins[i]?.elevation_m ?? meanElev) - meanElev) * ELEVATION_SCALE);
  const out: number[] = [];
  for (let i = 0; i < N; i++) {
    const pt = centerline[i]!;
    const z = zAt(i);
    const iPrev = Math.max(0, i - 1);
    const iNext = Math.min(N - 1, i + 1);
    const dx = centerline[iNext]!.x - centerline[iPrev]!.x;
    const dy = centerline[iNext]!.y - centerline[iPrev]!.y;
    const dz = zAt(iNext) - zAt(iPrev);
    const xyLen = Math.hypot(dx, dy) || 1;
    const ux = dx / xyLen;
    const uy = dy / xyLen;
    // N = T × B, T=(dx,dy,dz), B=(-uy,ux,0) → (-dz·ux, -dz·uy, xyLen)
    let nx = -dz * ux;
    let ny = -dz * uy;
    let nz = dx * ux + dy * uy; // = xyLen, always positive → N points +z
    const nLen = Math.hypot(nx, ny, nz) || 1;
    nx /= nLen; ny /= nLen; nz /= nLen;
    out.push(pt.x + nx * eps, pt.y + ny * eps, z + nz * eps);
  }
  return out;
}

/* ── Camera framing: see EXEC-2 OrbitControls + fit-to-bbox effects
 *    inside Scene. The legacy hand-rolled spherical useAutoFit rig was
 *    removed (no listener cleanup → leak) in favour of three/addons
 *    OrbitControls + an orthographic isometric fit. */

/* ── Scene content ────────────────────────────────────── */

interface SceneProps {
  bins: SurfaceBin[];
  mode: HeatmapMode;
  gpsXY: XYPoint[] | null;
  gpsDistances: number[] | null;
  optimalLine: OptimalLinePoint[] | null;
  lineDelta: LineDeltaPoint[] | null;
  conditions: WeatherConditionBlock | null | undefined;
  spatialFactor: SpatialFactor;
  showOptimalLine: boolean;
  showActualLine: boolean;
  // Stage 1 Path F — literal hand-traced edges from API. When present
  // (track has gt_*.geojson + session has GPS), the renderer triangulates
  // directly between these edges; mesh boundary == hand-tracing by
  // construction. Null → fall back to legacy spine±width ribbon.
  leftEdgeXyLocal: [number, number][] | null;
  rightEdgeXyLocal: [number, number][] | null;
  leftEdgeSn: [number, number][] | null;
  rightEdgeSn: [number, number][] | null;
  midlineLengthM: number | null;
  // Stage 1 medial-axis M×K grid (preferred over literal-edge when present).
  meshSpineXy: [number, number][] | null;
  meshLXy: [number, number][] | null;
  meshRXy: [number, number][] | null;
  meshSpineS: number[] | null;
  meshHwL: number[] | null;
  meshHwR: number[] | null;
  meshM: number | null;
  meshK: number | null;
  // PRIMARY render path: constrained Delaunay triangulation. M×K, literal-
  // edge and spine±width all stay as dispatcher fallbacks below it.
  meshTriXy: [number, number][] | null;
  meshTriIndices: [number, number, number][] | null;
  meshTriSn: [number, number][] | null;
  meshTriGrip: number[] | null;
  meshTriSpeed: (number | null)[] | null;
  // Stable, lap-INDEPENDENT geometry identity for the camera fit. Switching
  // laps refetches the surface (new object refs → surfaceGeo rebuilds), but
  // fitKey stays constant, so the isometric framing does NOT reset on a lap
  // change (EXEC-5 gate). Changes only when the actual track/geometry does.
  fitKey: string | number;
}

function Scene({
  bins, mode, gpsXY, gpsDistances, optimalLine, lineDelta, conditions,
  spatialFactor, showOptimalLine, showActualLine,
  leftEdgeXyLocal, rightEdgeXyLocal, leftEdgeSn, rightEdgeSn, midlineLengthM,
  meshSpineXy, meshLXy, meshRXy, meshSpineS, meshHwL, meshHwR, meshM, meshK,
  meshTriXy, meshTriIndices, meshTriSn, meshTriGrip, meshTriSpeed, fitKey,
}: SceneProps) {
  const { camera, gl, size } = useThree();
  const controlsRef = useRef<OrbitControls | null>(null);

  const centerline = useMemo(
    () => buildCenterline(bins, gpsXY, gpsDistances),
    [bins, gpsXY, gpsDistances],
  );

  const heatValues = useMemo(
    () => binHeatValues(bins, mode, lineDelta, conditions, spatialFactor),
    [bins, mode, lineDelta, conditions, spatialFactor],
  );

  // Day-13 Phase D — per-edge 2D field sampling. null when 2D fields
  // aren't available; buildSurfaceGeometry then falls back to 1D
  // (single color per bin, both edge vertices identical).
  const edgeValues = useMemo(
    () =>
      mode === 'spatial-grip'
        ? binEdgeHeatValuesFromField2D(bins, conditions, spatialFactor)
        : null,
    [bins, mode, conditions, spatialFactor],
  );

  // Render dispatcher, in priority order:
  //   1) Constrained Delaunay triangulation (PRIMARY) — touches both
  //      kerbs, non-inverting by construction, per-vertex grip from
  //      the 2D field where available, 1d_fallback elsewhere.
  //   2) M×K medial-axis grid — Stage 1 structured fallback (known
  //      to invert at apex; kept for tracks without a triangulation).
  //   3) Literal-edge ribbon (Path F) — pre-Stage-1 fallback.
  //   4) Legacy spine ± width — no gt available.
  // Each preference is dispatched on null-check of its inputs.
  const surfaceGeo = useMemo(() => {
    if (
      meshTriXy && meshTriIndices && meshTriGrip && meshTriSn
      && meshTriXy.length >= 3
      && meshTriIndices.length >= 1
    ) {
      return buildTriangulatedSurface(
        meshTriXy, meshTriIndices, meshTriSn, bins,
      );
    }
    if (
      meshSpineXy && meshLXy && meshRXy
      && meshSpineS && meshHwL && meshHwR
      && meshM != null && meshK != null
      && meshSpineXy.length >= 2
    ) {
      return buildMxKMesh(
        meshSpineXy, meshLXy, meshRXy,
        meshSpineS, meshHwL, meshHwR,
        meshK, bins, mode, conditions, spatialFactor,
      );
    }
    if (
      leftEdgeXyLocal && rightEdgeXyLocal
      && leftEdgeXyLocal.length >= 2
      && rightEdgeXyLocal.length >= 2
      && midlineLengthM != null && midlineLengthM > 0
    ) {
      return buildLiteralEdgeMesh(
        leftEdgeXyLocal, rightEdgeXyLocal,
        leftEdgeSn, rightEdgeSn,
        bins, heatValues, mode, conditions, spatialFactor,
        midlineLengthM,
      );
    }
    return buildSurfaceGeometry(centerline, bins, heatValues, mode, edgeValues);
  }, [
    meshTriXy, meshTriIndices, meshTriGrip, meshTriSn,
    meshSpineXy, meshLXy, meshRXy, meshSpineS, meshHwL, meshHwR, meshM, meshK,
    leftEdgeXyLocal, rightEdgeXyLocal, leftEdgeSn, rightEdgeSn, midlineLengthM,
    centerline, bins, heatValues, mode, edgeValues, conditions, spatialFactor,
  ]);

  // EXEC-4: per-mode vertex-colour buffers (Delaunay path only — keyed
  // on the per-vertex mesh_tri_grip set). null for fallback paths, which
  // keep their own baked colour. speed/gradient are grey stubs until
  // EXEC-7/EXEC-6 populate them.
  const colorBuffers = useMemo(() => {
    if (!meshTriGrip || meshTriGrip.length === 0) return null;
    // Degenerate grip → grey. isGripAvailable() is shared with the panel
    // (which calls it on surface.mesh_tri_grip to disable the GRIP control
    // and pick the default mode) so the two can never disagree.
    const avail = isGripAvailable(meshTriGrip);
    const n = meshTriGrip.length;
    return {
      grip: avail ? makeColorBuffer(meshTriGrip, GRIP_STOPS, [0.5, 1.1]) : greyBuffer(n),
      speed: meshTriSpeed && meshTriSpeed.length === n
        ? makeColorBuffer(meshTriSpeed, SPEED_STOPS, finiteDomain(meshTriSpeed))
        : greyBuffer(n),
      gradient: meshTriSn && meshTriSn.length === n
        ? buildGradientBuffer(meshTriSn, bins)
        : greyBuffer(n),
    };
  }, [meshTriGrip, meshTriSpeed, meshTriSn, bins]);

  // Mode swap: set the colour attribute from the active mode's buffer
  // WITHOUT rebuilding geometry. Guarded by vertex-count match so it
  // only touches the Delaunay surface (fallback paths keep baked colour).
  useEffect(() => {
    if (!colorBuffers) return;
    const posCount = surfaceGeo.attributes.position?.count ?? 0;
    const buf =
      mode === 'speed' ? colorBuffers.speed
      : mode === 'gradient' ? colorBuffers.gradient
      : colorBuffers.grip;
    if (!buf || buf.length !== posCount * 3) return;
    surfaceGeo.setAttribute('color', new THREE.BufferAttribute(buf, 3));
    surfaceGeo.attributes.color.needsUpdate = true;
  }, [surfaceGeo, mode, colorBuffers]);

  // EXEC-3: lit relief. MeshLambertMaterial + per-vertex normals shades
  // adjacent triangles as one continuous membrane; polygonOffset pushes
  // the fill back so the racing-line/edge overlays sit cleanly on top.
  const surfaceMat = useMemo(() => {
    const lowConfidence =
      mode === 'spatial-grip' &&
      typeof conditions?.confidence === 'number' &&
      conditions.confidence < SPATIAL_GRIP_LOW_CONFIDENCE;
    return new THREE.MeshLambertMaterial({
      vertexColors: true,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
      transparent: lowConfidence,
      opacity: lowConfidence ? 0.6 : 1.0,
    });
  }, [mode, conditions?.confidence]);

  // Path F edge outline tubes — thick black boundaries along the
  // hand-traced left + right polylines when the literal-edge mesh is
  // active. Null when on the legacy spine-ribbon path (no literal edges
  // to outline). WebGL doesn't render thick lines reliably so we use
  // 3D tubes for visual thickness.
  const leftEdgeTube = useMemo(
    () =>
      leftEdgeXyLocal && leftEdgeXyLocal.length >= 2
        ? buildEdgeTubeGeometry(leftEdgeXyLocal, leftEdgeSn, bins, 0.5, 0.15)
        : null,
    [leftEdgeXyLocal, leftEdgeSn, bins],
  );
  const rightEdgeTube = useMemo(
    () =>
      rightEdgeXyLocal && rightEdgeXyLocal.length >= 2
        ? buildEdgeTubeGeometry(rightEdgeXyLocal, rightEdgeSn, bins, 0.5, 0.15)
        : null,
    [rightEdgeXyLocal, rightEdgeSn, bins],
  );
  const edgeTubeMat = useMemo(
    () => new THREE.MeshBasicMaterial({ color: 0x000000 }),
    [],
  );

  // Optimal line geometry
  const optimalGeo = useMemo(() => {
    if (!showOptimalLine || !optimalLine || optimalLine.length === 0) return null;
    // Resample optimal line offsets to match bin distances
    const offsets: number[] = [];
    let oIdx = 0;
    for (const bin of bins) {
      while (oIdx < optimalLine.length - 2 && optimalLine[oIdx + 1]!.distance_m < bin.distance_m) {
        oIdx++;
      }
      offsets.push(optimalLine[oIdx]?.lateral_offset_m ?? 0);
    }
    return buildLineGeometry(centerline, offsets, bins, 0.3);
  }, [showOptimalLine, optimalLine, centerline, bins]);

  // EXEC-8: the actual driven line (selected lap) as a fat Line2 ribbon that
  // floats just above the surface. Lifted along the estimated surface normal
  // by ε = 0.004·zspan; renderOrder=1 + depthWrite=false + the surface's
  // polygonOffset keep it from z-fighting on slopes. Rebuilt only when the
  // path/geometry changes (resolution is updated separately on resize).
  const actualLine2 = useMemo(() => {
    if (!showActualLine || centerline.length < 2) return null;
    const bb = surfaceGeo.boundingBox;
    const zspan = bb ? bb.max.z - bb.min.z : 0;
    const eps = Math.max(0.004 * zspan, 0.01);
    const positions = buildDrivenLinePositions(centerline, bins, eps);
    if (positions.length < 6) return null;
    const geo = new LineGeometry();
    geo.setPositions(positions);
    const mat = new LineMaterial({
      color: CHALK,
      linewidth: 3,
      worldUnits: false,
      transparent: true,
      depthWrite: false,
    });
    const line = new Line2(geo, mat);
    line.renderOrder = 1;
    return line;
  }, [showActualLine, centerline, bins, surfaceGeo]);

  // LineMaterial needs the viewport resolution or it renders ~1px. Update on
  // mount + every resize, separate from the geometry build so a resize
  // doesn't rebuild the line's GPU buffers.
  useEffect(() => {
    if (actualLine2) {
      (actualLine2.material as LineMaterial).resolution.set(size.width || 1, size.height || 1);
    }
  }, [actualLine2, size.width, size.height]);

  // Dispose the previous fat line's GPU buffers when it is replaced/unmounted.
  useEffect(() => {
    return () => {
      if (actualLine2) {
        actualLine2.geometry.dispose();
        (actualLine2.material as LineMaterial).dispose();
      }
    };
  }, [actualLine2]);

  const optimalLineMat = useMemo(
    () => new THREE.LineBasicMaterial({ color: GOLD, linewidth: 2 }),
    [],
  );

  // EXEC-2: OrbitControls (imperative — three/addons class, instantiated
  // directly rather than via extend()+<orbitControls> JSX). Identical
  // end-state to the declarative form but avoids r3f-8.18 JSX-intrinsic
  // typing/registration risk. z-up scene (positions are [x, y, elev]).
  useEffect(() => {
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, gl.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    controls.minPolarAngle = 0.05;
    controls.maxPolarAngle = Math.PI / 2 - 0.02;
    controlsRef.current = controls;
    return () => {
      controls.dispose();
      controlsRef.current = null;
    };
  }, [camera, gl]);

  // Fit-to-bbox isometric framing — once per geometry change (keyed on
  // surfaceGeo identity, NOT on resize, so user orbit isn't reset).
  useEffect(() => {
    const controls = controlsRef.current;
    const cam = camera as THREE.OrthographicCamera;
    if (!surfaceGeo.boundingBox) surfaceGeo.computeBoundingBox();
    const box = surfaceGeo.boundingBox;
    if (!box || !cam.isOrthographicCamera) return;
    const center = new THREE.Vector3();
    box.getCenter(center);
    const sphere = new THREE.Sphere();
    box.getBoundingSphere(sphere);
    const r = Math.max(sphere.radius, 1);
    const w = gl.domElement.clientWidth || 1;
    const h = gl.domElement.clientHeight || 1;
    // 3/4 isometric: camera offset along (1,1,1) by 4r; ortho zoom frames
    // the bounding sphere into the smaller viewport dimension at 90%.
    cam.position.copy(center).add(new THREE.Vector3(1, 1, 1).normalize().multiplyScalar(r * 4));
    cam.zoom = (Math.min(w, h) / (2 * r)) * 0.9;
    cam.near = 0.1;
    cam.far = r * 20;
    cam.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    } else {
      cam.lookAt(center);
    }
    // Keyed on fitKey (lap-independent geometry identity), NOT surfaceGeo:
    // a lap switch rebuilds surfaceGeo but must not re-frame the camera.
    // surfaceGeo is read via closure (its bbox is identical across laps).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, camera, gl]);

  // Damping needs a per-frame update.
  useFrame(() => {
    controlsRef.current?.update();
  });

  return (
    <>
      {/* Track surface mesh — single continuous membrane.
       *  Per-vertex grip vertexColors interpolate smoothly across each
       *  triangle (Gouraud); MeshBasicMaterial is unlit so there are
       *  no facet steps from per-face normals either. */}
      <mesh frustumCulled={false}>
        <primitive object={surfaceGeo} attach="geometry" />
        <primitive object={surfaceMat} attach="material" />
      </mesh>
      {leftEdgeTube && (
        <mesh frustumCulled={false}>
          <primitive object={leftEdgeTube} attach="geometry" />
          <primitive object={edgeTubeMat} attach="material" />
        </mesh>
      )}
      {rightEdgeTube && (
        <mesh frustumCulled={false}>
          <primitive object={rightEdgeTube} attach="geometry" />
          <primitive object={edgeTubeMat} attach="material" />
        </mesh>
      )}

      {/* Optimal racing line — flagged off for this ship (EXEC-8). */}
      {SHOW_OPTIMAL_LINE && optimalGeo && (
        <line frustumCulled={false}>
          <primitive object={optimalGeo} attach="geometry" />
          <primitive object={optimalLineMat} attach="material" />
        </line>
      )}

      {/* Actual driven line (selected lap) — EXEC-8 fat Line2 ribbon. */}
      {actualLine2 && <primitive object={actualLine2} />}

      {/* EXEC-3: ambient fill + one directional light so Lambert shades
       *  the elevation relief. Direction matters (z-up scene), not
       *  magnitude. */}
      <ambientLight intensity={0.55} />
      <directionalLight position={[0.4, 0.6, 1]} intensity={1.15} />
    </>
  );
}

/* ── EXEC-1: verification oracle ──────────────────────────
 * Mounted inside <Canvas>. One rAF after each surface-data change it
 * console.asserts the invariants every downstream EXEC depends on, and
 * exposes window.__surfacePNG() for a deterministic console screenshot.
 * This is the tool that proves EXEC-2..10 didn't silently break the
 * render — it must go green on a known-good KCT session first. */
function DebugAsserts({ dep }: { dep: string | number | null }) {
  const { gl, scene } = useThree();

  useEffect(() => {
    if (typeof window !== 'undefined') {
      (window as { __surfacePNG?: () => string }).__surfacePNG = () =>
        gl.domElement.toDataURL('image/png');
    }
    const raf = requestAnimationFrame(() => {
      const tris = gl.info.render.triangles;
      console.assert(tris > 0, 'ASSERT_FAIL: no triangles drawn');

      let maxZSpan = 0;
      let reliefOK = false;
      let nanAttr = '';
      let vertTotal = 0;
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!(mesh as unknown as { isMesh?: boolean }).isMesh || !mesh.geometry) return;
        const g = mesh.geometry as THREE.BufferGeometry;
        if (!g.boundingBox) g.computeBoundingBox();
        const bb = g.boundingBox;
        if (bb && Number.isFinite(bb.max.z) && Number.isFinite(bb.min.z)) {
          const span = bb.max.z - bb.min.z;
          if (span > maxZSpan) maxZSpan = span;
          if (span > 0) reliefOK = true;
        }
        const pos = g.attributes.position?.array;
        if (pos) {
          vertTotal += pos.length / 3;
          for (let i = 0; i < pos.length; i++) {
            if (Number.isNaN(pos[i]!)) { nanAttr = 'position'; break; }
          }
        }
        const col = g.attributes.color?.array;
        if (col && !nanAttr) {
          for (let i = 0; i < col.length; i++) {
            if (Number.isNaN(col[i]!)) { nanAttr = 'color'; break; }
          }
        }
      });

      console.assert(reliefOK, 'ASSERT_FAIL: no elevation relief');
      console.assert(!nanAttr, `ASSERT_FAIL: NaN in ${nanAttr}`);

      if (tris > 0 && reliefOK && !nanAttr) {
        // eslint-disable-next-line no-console
        console.log(`[SURF-OK] tris=${tris} zspan=${maxZSpan.toFixed(3)} verts=${vertTotal}`);
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [gl, scene, dep]);

  return null;
}

/* ── Main exported component ──────────────────────────── */

export function TrackSurface3D({
  sessionId,
  lap = null,
  mode = 'grip',
  spatialFactor = 'combined',
  showOptimalLine = true,
  showActualLine = false,
  className,
}: TrackSurface3DProps) {
  const { surface, optimalLine, gpsTrace, lineDelta, isLoading, error } = useTrackSurfaceData(sessionId, lap);

  // Guard: /gps-trace can return 200 with {available: false} for sessions
  // without a GPS lap; gpsTrace.latitudes is then undefined. Without the
  // Array.isArray check, gpsToLocalXY throws "Cannot read properties of
  // undefined (reading 'length')" because this useMemo runs BEFORE the
  // early-return surface guard below — so the entire panel crashes before
  // we ever get to "show empty state."
  const gpsXY = useMemo(() => {
    if (
      !gpsTrace
      || !Array.isArray(gpsTrace.latitudes)
      || !Array.isArray(gpsTrace.longitudes)
      || gpsTrace.latitudes.length === 0
    ) {
      return null;
    }
    return gpsToLocalXY(gpsTrace.latitudes, gpsTrace.longitudes);
  }, [gpsTrace]);

  const gpsDistances = Array.isArray(gpsTrace?.distances) ? gpsTrace!.distances : null;

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center bg-concrete rounded-lg ${className ?? ''}`}>
        <p className="font-telemetry text-steel text-sm">Loading surface data...</p>
      </div>
    );
  }

  // 404 on /track-surface = session has no recognised track (no aggregate
  // surface for its track_id). Distinct from other failure modes (auth,
  // network). Render graceful empty state — NEVER fall through to the
  // Canvas / Scene path, where any builder reading .length on the
  // missing surface arrays would throw.
  const is404 = !!(
    error
    && typeof error === 'object'
    && 'status' in error
    && (error as { status: unknown }).status === 404
  );
  if (is404) {
    return (
      <div className={`flex items-center justify-center bg-concrete rounded-lg ${className ?? ''}`}>
        <p className="font-telemetry text-steel text-sm">
          Track not recognized — no surface for this session
        </p>
      </div>
    );
  }
  if (
    error
    || !surface
    || !Array.isArray(surface.bins)
    || surface.bins.length < 2
  ) {
    return (
      <div className={`flex items-center justify-center bg-concrete rounded-lg ${className ?? ''}`}>
        <p className="font-telemetry text-safety-red text-sm">
          {error ? 'Failed to load track surface data' : 'Insufficient surface data'}
        </p>
      </div>
    );
  }

  // EXEC-9: a surface with bins but no way to place it in space — no gt mesh
  // (tri / M×K / literal-edge) AND no GPS centreline — would otherwise collapse
  // to the degenerate straight-X ribbon. Show the clean empty state instead.
  const hasMeshTri = Array.isArray(surface.mesh_tri_xy) && surface.mesh_tri_xy.length >= 3;
  const hasMxK = Array.isArray(surface.mesh_spine_xy) && surface.mesh_spine_xy.length >= 2;
  const hasLiteralEdge =
    Array.isArray(surface.left_edge_xy_local) && surface.left_edge_xy_local.length >= 2
    && Array.isArray(surface.right_edge_xy_local) && surface.right_edge_xy_local.length >= 2;
  const hasGpsCentreline = Array.isArray(gpsXY) && gpsXY.length >= 2;
  if (!hasMeshTri && !hasMxK && !hasLiteralEdge && !hasGpsCentreline) {
    return (
      <div className={`flex items-center justify-center bg-concrete rounded-lg ${className ?? ''}`}>
        <p className="font-telemetry text-steel text-sm">
          No spatial trace for this session — surface can’t be placed
        </p>
      </div>
    );
  }

  return (
    <div className={`bg-asphalt rounded-lg overflow-hidden ${className ?? ''}`}>
      <Canvas
        orthographic
        camera={{ near: 0.1, far: 10000, position: [1, 1, 1], zoom: 10 }}
        gl={{ antialias: true, alpha: false, preserveDrawingBuffer: true }}
        style={{ background: '#000000' }}
      >
        <DebugAsserts dep={surface.mesh_tri_sha256 ?? surface.bins.length} />
        <Scene
          bins={surface.bins}
          mode={mode}
          gpsXY={gpsXY}
          gpsDistances={gpsDistances}
          optimalLine={optimalLine}
          lineDelta={lineDelta}
          conditions={surface.conditions ?? null}
          spatialFactor={spatialFactor}
          leftEdgeXyLocal={surface.left_edge_xy_local ?? null}
          rightEdgeXyLocal={surface.right_edge_xy_local ?? null}
          leftEdgeSn={surface.left_edge_sn ?? null}
          rightEdgeSn={surface.right_edge_sn ?? null}
          midlineLengthM={surface.midline_total_length_m ?? null}
          meshSpineXy={surface.mesh_spine_xy ?? null}
          meshLXy={surface.mesh_L_xy ?? null}
          meshRXy={surface.mesh_R_xy ?? null}
          meshSpineS={surface.mesh_spine_s ?? null}
          meshHwL={surface.mesh_hw_L ?? null}
          meshHwR={surface.mesh_hw_R ?? null}
          meshM={surface.mesh_M ?? null}
          meshK={surface.mesh_K ?? null}
          meshTriXy={surface.mesh_tri_xy ?? null}
          meshTriIndices={surface.mesh_tri_indices ?? null}
          meshTriSn={surface.mesh_tri_sn ?? null}
          meshTriGrip={surface.mesh_tri_grip ?? null}
          meshTriSpeed={surface.mesh_tri_speed ?? null}
          fitKey={surface.mesh_tri_sha256 ?? surface.bins.length}
          showOptimalLine={showOptimalLine}
          showActualLine={showActualLine}
        />
      </Canvas>
    </div>
  );
}
