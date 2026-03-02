import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import type {
  CornerReplayData,
  CornerReplayTrace,
  AnalyzerTrace,
  SectionDef,
} from './types';

/* ── Haversine distance between two GPS points (meters) ──── */

function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/* ── Build cumulative distance array from lat/lon ─────────── */

function buildDistanceArray(lat: number[], lon: number[]): number[] {
  const n = lat.length;
  const dist = new Array<number>(n);
  dist[0] = 0;
  for (let i = 1; i < n; i++) {
    dist[i] = dist[i - 1] + haversine(lat[i - 1], lon[i - 1], lat[i], lon[i]);
  }
  return dist;
}

/* ── Convert raw API trace to AnalyzerTrace ───────────────── */

function toAnalyzerTrace(
  lapNumber: number,
  raw: CornerReplayTrace,
  lapTime: number | null,
): AnalyzerTrace {
  const n = raw.lat.length;
  const distance = raw.dist_m?.length === n ? raw.dist_m : buildDistanceArray(raw.lat, raw.lon);
  const empty = new Array<number>(n).fill(0);

  return {
    lapNumber,
    lat: raw.lat,
    lon: raw.lon,
    distance,
    speed: raw.speed_mps.map((v) => v * 3.6), // m/s → km/h
    gLat: raw.accel_lat ?? empty,
    gLon: raw.accel_lon ?? empty,
    brake: raw.brake ?? empty,
    throttle: raw.throttle ?? empty,
    steering: raw.steering ?? empty,
    lapTime,
  };
}

/* ── Binary search: find index closest to target in sorted array */

export function closestIndex(arr: number[], target: number): number {
  if (!arr || arr.length === 0) return 0;
  let lo = 0;
  let hi = arr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) return lo - 1;
  return lo;
}

/* ── Build section definitions from corners ────────────────── */

function buildSections(
  corners: { corner_id: string; label: string; dist_m: number }[],
  maxDist: number,
): SectionDef[] {
  if (corners.length === 0) {
    return [{ id: 'full', label: 'Full Track', startDist: 0, endDist: maxDist, type: 'full' }];
  }

  // Sort corners by distance
  const sorted = [...corners].sort((a, b) => a.dist_m - b.dist_m);

  const sections: SectionDef[] = [
    { id: 'full', label: 'Full Track', startDist: 0, endDist: maxDist, type: 'full' },
  ];

  // Estimate corner width as 15% of average inter-corner spacing (clamped 20-150m)
  const avgSpacing = maxDist / Math.max(1, sorted.length);
  const halfWidth = Math.max(20, Math.min(150, avgSpacing * 0.15));

  let prevEnd = 0;
  for (let i = 0; i < sorted.length; i++) {
    const c = sorted[i];
    const cStart = Math.max(prevEnd, c.dist_m - halfWidth);
    const cEnd = Math.min(maxDist, c.dist_m + halfWidth);

    // Straight before this corner
    if (cStart > prevEnd + 10) {
      sections.push({
        id: `S${i + 1}`,
        label: `S${i + 1}`,
        startDist: prevEnd,
        endDist: cStart,
        type: 'straight',
      });
    }

    // The corner itself
    sections.push({
      id: `T${i + 1}`,
      label: c.label || `T${i + 1}`,
      startDist: cStart,
      endDist: cEnd,
      type: 'corner',
      cornerIndex: i,
    });

    prevEnd = cEnd;
  }

  // Final straight
  if (prevEnd < maxDist - 10) {
    sections.push({
      id: `S${sorted.length + 1}`,
      label: `S${sorted.length + 1}`,
      startDist: prevEnd,
      endDist: maxDist,
      type: 'straight',
    });
  }

  return sections;
}

/* ── Interpolate delta time between two traces at equal distances ── */

export function computeDelta(
  primary: AnalyzerTrace,
  reference: AnalyzerTrace,
): { distances: number[]; deltas: number[] } {
  // Use the primary's distance array as the x-axis
  const distances = primary.distance;
  const deltas = new Array<number>(distances.length);

  // Build time arrays from speed (integral of 1/speed over distance)
  const timeA = cumulativeTime(primary.distance, primary.speed);
  const timeB = cumulativeTime(reference.distance, reference.speed);

  for (let i = 0; i < distances.length; i++) {
    const d = distances[i];
    const tA = timeA[i];
    const tB = interpolateAtDistance(reference.distance, timeB, d);
    deltas[i] = tB - tA; // positive = primary faster
  }

  return { distances, deltas };
}

function cumulativeTime(dist: number[], speedKmh: number[]): number[] {
  const n = dist.length;
  const time = new Array<number>(n);
  time[0] = 0;
  for (let i = 1; i < n; i++) {
    const ds = dist[i] - dist[i - 1];
    const speedMs = ((speedKmh[i - 1] + speedKmh[i]) / 2) / 3.6;
    time[i] = time[i - 1] + (speedMs > 0.1 ? ds / speedMs : 0);
  }
  return time;
}

function interpolateAtDistance(dist: number[], values: number[], target: number): number {
  const idx = closestIndex(dist, target);
  if (idx <= 0) return values[0];
  if (idx >= dist.length - 1) return values[dist.length - 1];

  // Linear interpolation
  const d0 = dist[idx - 1];
  const d1 = dist[idx];
  const range = d1 - d0;
  if (range < 0.001) return values[idx];
  const t = (target - d0) / range;
  return values[idx - 1] + t * (values[idx] - values[idx - 1]);
}

/* ── Main data hook ───────────────────────────────────────── */

export function useAnalyzerData(sessionId: string, cornerFilter?: number[]) {
  const cornerParam = cornerFilter?.length ? `?corners=${cornerFilter.join(',')}` : '?corners=all';

  const { data: raw, isLoading, error } = useQuery({
    queryKey: ['driving-analyzer', sessionId, cornerFilter?.join(',') ?? 'all'],
    queryFn: () => api.get<CornerReplayData>(`/sessions/${sessionId}/corner-replay${cornerParam}`),
    enabled: !!sessionId,
    staleTime: 5 * 60 * 1000,
  });

  // Process traces
  const traces = useMemo<Record<string, AnalyzerTrace>>(() => {
    if (!raw) return {};
    const result: Record<string, AnalyzerTrace> = {};
    const lapMap = new Map(raw.laps.map((l) => [l.lap_number, l.lap_time_s]));

    for (const [key, trace] of Object.entries(raw.traces)) {
      const lapNum = Number(key);
      result[key] = toAnalyzerTrace(lapNum, trace, lapMap.get(lapNum) ?? null);
    }
    return result;
  }, [raw]);

  // Build sections from corners
  const sections = useMemo<SectionDef[]>(() => {
    if (!raw || Object.keys(traces).length === 0) return [];
    // Use the first available trace to determine max distance
    const firstTrace = Object.values(traces)[0];
    const maxDist = firstTrace ? firstTrace.distance[firstTrace.distance.length - 1] : 0;
    return buildSections(raw.corners, maxDist);
  }, [raw, traces]);

  // Available laps
  const laps = useMemo(() => raw?.laps ?? [], [raw]);

  // Channel availability
  const hasPedalData = raw?.has_pedal_data ?? false;
  const hasSteeringData = raw?.has_steering_data ?? false;

  return {
    raw,
    traces,
    sections,
    laps,
    hasPedalData,
    hasSteeringData,
    isLoading,
    error,
  };
}
