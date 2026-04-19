'use client';

import { useCallback, useMemo, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { useTrackSurfaceData, type SurfaceBin, type OptimalLinePoint, type LineDeltaPoint } from './useTrackSurfaceData';

/* ── Heatmap palette hex values (WebGL, not CSS tokens) ── */

const COLORS = {
  grip: { high: 0x22C55E, low: 0xFF2A2A },
  elevation: { high: 0xF0EDE5, low: 0x3B82F6 },
  'line-delta': { high: 0x22C55E, low: 0xFF2A2A },
} as const;

const GOLD = 0xC9A84C;
const CHALK = 0xF0EDE5;
const DEFAULT_TRACK_WIDTH = 8; // metres fallback

/* ── Types ────────────────────────────────────────────── */

export type HeatmapMode = 'grip' | 'elevation' | 'line-delta';

export interface TrackSurface3DProps {
  sessionId: string;
  mode?: HeatmapMode;
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
): number[] {
  if (mode === 'grip') {
    let minMu = Infinity;
    let maxMu = -Infinity;
    for (const b of bins) { minMu = Math.min(minMu, b.grip_mu); maxMu = Math.max(maxMu, b.grip_mu); }
    const range = maxMu - minMu || 1;
    return bins.map((b) => (b.grip_mu - minMu) / range);
  }

  if (mode === 'elevation') {
    let minE = Infinity;
    let maxE = -Infinity;
    for (const b of bins) { minE = Math.min(minE, b.elevation_m); maxE = Math.max(maxE, b.elevation_m); }
    const range = maxE - minE || 1;
    return bins.map((b) => (b.elevation_m - minE) / range);
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

/* ── Ribbon mesh geometry builder ─────────────────────── */

function buildSurfaceGeometry(
  centerline: CenterlinePoint[],
  bins: SurfaceBin[],
  heatValues: number[],
  mode: HeatmapMode,
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

  for (let i = 0; i < count; i++) {
    const pt = centerline[i]!;
    const bin = bins[i]!;
    const halfW = (bin.width_m ?? DEFAULT_TRACK_WIDTH) / 2;
    const elev = bin.elevation_m * 0.5; // scale elevation for visibility

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
    // Normal (perpendicular in XY): rotate tangent 90 degrees
    const nx = -ty / tLen;
    const ny = tx / tLen;

    const li = i * 2;
    const ri = i * 2 + 1;

    positions[li * 3] = pt.x - nx * halfW;
    positions[li * 3 + 1] = pt.y - ny * halfW;
    positions[li * 3 + 2] = elev;
    positions[ri * 3] = pt.x + nx * halfW;
    positions[ri * 3 + 1] = pt.y + ny * halfW;
    positions[ri * 3 + 2] = elev;

    // Vertex color from heat value
    const t = heatValues[i] ?? 0.5;
    tmpColor.copy(colLow).lerp(colHigh, t);
    colors[li * 3] = tmpColor.r;
    colors[li * 3 + 1] = tmpColor.g;
    colors[li * 3 + 2] = tmpColor.b;
    colors[ri * 3] = tmpColor.r;
    colors[ri * 3 + 1] = tmpColor.g;
    colors[ri * 3 + 2] = tmpColor.b;
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
  geo.computeBoundingSphere();
  return geo;
}

/* ── Line geometry builder ────────────────────────────── */

function buildLineGeometry(
  centerline: CenterlinePoint[],
  offsets: number[] | null,
  elevationBins: SurfaceBin[],
  liftZ: number,
): THREE.BufferGeometry {
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
    const elev = (elevationBins[i]?.elevation_m ?? 0) * 0.5 + liftZ;
    pts.push(pt.x + nx * offset, pt.y + ny * offset, elev);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  return geo;
}

/* ── Auto-fit camera to geometry bounds ───────────────── */

function useAutoFit(
  centerline: CenterlinePoint[],
  cameraState: React.MutableRefObject<{ target: THREE.Vector3; radius: number }>,
) {
  const fitted = useRef(false);
  if (centerline.length > 1 && !fitted.current) {
    let minX = Infinity; let maxX = -Infinity;
    let minY = Infinity; let maxY = -Infinity;
    for (const pt of centerline) {
      minX = Math.min(minX, pt.x); maxX = Math.max(maxX, pt.x);
      minY = Math.min(minY, pt.y); maxY = Math.max(maxY, pt.y);
    }
    cameraState.current.target.set((minX + maxX) / 2, (minY + maxY) / 2, 0);
    const span = Math.max(maxX - minX, maxY - minY, 20);
    cameraState.current.radius = span * 0.8;
    fitted.current = true;
  }
}

/* ── Scene content ────────────────────────────────────── */

interface SceneProps {
  bins: SurfaceBin[];
  mode: HeatmapMode;
  gpsXY: XYPoint[] | null;
  gpsDistances: number[] | null;
  optimalLine: OptimalLinePoint[] | null;
  lineDelta: LineDeltaPoint[] | null;
  showOptimalLine: boolean;
  showActualLine: boolean;
}

function Scene({
  bins, mode, gpsXY, gpsDistances, optimalLine, lineDelta, showOptimalLine, showActualLine,
}: SceneProps) {
  const { camera, gl } = useThree();
  const orbitState = useRef({
    isDragging: false,
    prevX: 0,
    prevY: 0,
    theta: Math.PI / 4,
    phi: Math.PI / 3,
    radius: 100,
    target: new THREE.Vector3(0, 0, 0),
  });

  const centerline = useMemo(
    () => buildCenterline(bins, gpsXY, gpsDistances),
    [bins, gpsXY, gpsDistances],
  );

  useAutoFit(centerline, orbitState);

  const heatValues = useMemo(() => binHeatValues(bins, mode, lineDelta), [bins, mode, lineDelta]);

  const surfaceGeo = useMemo(
    () => buildSurfaceGeometry(centerline, bins, heatValues, mode),
    [centerline, bins, heatValues, mode],
  );

  const surfaceMat = useMemo(
    () => new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide }),
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

  // Actual driving line geometry (offset = 0, on-center)
  const actualGeo = useMemo(() => {
    if (!showActualLine) return null;
    return buildLineGeometry(centerline, null, bins, 0.15);
  }, [showActualLine, centerline, bins]);

  const optimalLineMat = useMemo(
    () => new THREE.LineBasicMaterial({ color: GOLD, linewidth: 2 }),
    [],
  );
  const actualLineMat = useMemo(
    () => new THREE.LineBasicMaterial({ color: CHALK, linewidth: 1, transparent: true, opacity: 0.7 }),
    [],
  );

  // Manual orbit controls
  const onPointerDown = useCallback((e: PointerEvent) => {
    orbitState.current.isDragging = true;
    orbitState.current.prevX = e.clientX;
    orbitState.current.prevY = e.clientY;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: PointerEvent) => {
    if (!orbitState.current.isDragging) return;
    const dx = e.clientX - orbitState.current.prevX;
    const dy = e.clientY - orbitState.current.prevY;
    orbitState.current.prevX = e.clientX;
    orbitState.current.prevY = e.clientY;
    orbitState.current.theta -= dx * 0.005;
    orbitState.current.phi = Math.max(0.1, Math.min(Math.PI / 2 - 0.05, orbitState.current.phi - dy * 0.005));
  }, []);

  const onPointerUp = useCallback(() => {
    orbitState.current.isDragging = false;
  }, []);

  const onWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    orbitState.current.radius = Math.max(10, Math.min(500, orbitState.current.radius + e.deltaY * 0.1));
  }, []);

  // Attach pointer/wheel listeners once
  const attached = useRef(false);
  if (!attached.current && gl.domElement) {
    const el = gl.domElement;
    el.addEventListener('pointerdown', onPointerDown);
    el.addEventListener('pointermove', onPointerMove);
    el.addEventListener('pointerup', onPointerUp);
    el.addEventListener('pointerleave', onPointerUp);
    el.addEventListener('wheel', onWheel, { passive: false });
    attached.current = true;
  }

  useFrame(() => {
    const s = orbitState.current;
    const x = s.target.x + s.radius * Math.sin(s.phi) * Math.cos(s.theta);
    const y = s.target.y + s.radius * Math.sin(s.phi) * Math.sin(s.theta);
    const z = s.target.z + s.radius * Math.cos(s.phi);
    camera.position.set(x, y, z);
    camera.lookAt(s.target);
  });

  return (
    <>
      {/* Track surface mesh */}
      <mesh frustumCulled={false}>
        <primitive object={surfaceGeo} attach="geometry" />
        <primitive object={surfaceMat} attach="material" />
      </mesh>

      {/* Optimal racing line */}
      {optimalGeo && (
        <line frustumCulled={false}>
          <primitive object={optimalGeo} attach="geometry" />
          <primitive object={optimalLineMat} attach="material" />
        </line>
      )}

      {/* Actual driving line */}
      {actualGeo && (
        <line frustumCulled={false}>
          <primitive object={actualGeo} attach="geometry" />
          <primitive object={actualLineMat} attach="material" />
        </line>
      )}

      <ambientLight intensity={0.6} />
    </>
  );
}

/* ── Main exported component ──────────────────────────── */

export function TrackSurface3D({
  sessionId,
  mode = 'grip',
  showOptimalLine = true,
  showActualLine = false,
  className,
}: TrackSurface3DProps) {
  const { surface, optimalLine, gpsTrace, lineDelta, isLoading, error } = useTrackSurfaceData(sessionId);

  const gpsXY = useMemo(() => {
    if (!gpsTrace) return null;
    return gpsToLocalXY(gpsTrace.latitudes, gpsTrace.longitudes);
  }, [gpsTrace]);

  const gpsDistances = gpsTrace?.distances ?? null;

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center bg-concrete rounded-lg ${className ?? ''}`}>
        <p className="font-telemetry text-steel text-sm">Loading surface data...</p>
      </div>
    );
  }

  if (error || !surface || surface.bins.length < 2) {
    return (
      <div className={`flex items-center justify-center bg-concrete rounded-lg ${className ?? ''}`}>
        <p className="font-telemetry text-safety-red text-sm">
          {error ? 'Failed to load track surface data' : 'Insufficient surface data'}
        </p>
      </div>
    );
  }

  return (
    <div className={`bg-asphalt rounded-lg overflow-hidden ${className ?? ''}`}>
      <Canvas
        camera={{ fov: 50, near: 0.1, far: 2000 }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: '#000000' }}
      >
        <Scene
          bins={surface.bins}
          mode={mode}
          gpsXY={gpsXY}
          gpsDistances={gpsDistances}
          optimalLine={optimalLine}
          lineDelta={lineDelta}
          showOptimalLine={showOptimalLine}
          showActualLine={showActualLine}
        />
      </Canvas>
    </div>
  );
}
