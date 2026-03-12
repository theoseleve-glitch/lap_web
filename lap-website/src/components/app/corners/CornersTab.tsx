'use client';

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { CoachingTable } from './CoachingTable';
import { CornerReplay } from '../corner-replay';
import { BrakePrecisionChart } from './BrakePrecisionChart';
import { CornerMasteryCard } from './CornerMasteryCard';
import { ThrottleOnsetMap } from './ThrottleOnsetMap';
import { ConsistencyHeatmap } from './ConsistencyHeatmap';
import { CornerGHistogram } from './CornerGHistogram';
import { CornerSpeedTrend } from './CornerSpeedTrend';
import { CornerDefiner } from '../charts/CornerDefiner';
import { CornerPicker, type TrackLayout } from '../CornerPicker';

/* ── Types ──────────────────────────────────────────────── */

export interface HandlingEventData {
  event_type: 'understeer' | 'oversteer';
  severity: 'mild' | 'moderate' | 'severe';
  cause: string;
  cause_detail: string;
  corner_phase: 'entry' | 'mid' | 'exit';
  magnitude: number;
  time_cost_s?: number | null;
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
  /* v2 fields */
  corner_type?: string | null;
  section_type?: string | null;
  mrp_distance_m?: number | null;
  mrp_speed_mps?: number | null;
  geometric_apex_m?: number | null;
  exit_importance?: number | null;
  is_user_defined?: boolean | null;
  handling_events?: HandlingEventData[] | null;
}

interface CornerPosition {
  corner_id: number;
  s_start: number;
  s_end: number;
  s_apex?: number;
  direction?: string;
  lat: number;
  lon: number;
}

interface CornersTabProps {
  corners: CornerData[];
  sessionId: string;
}

type SubTab = 'coaching' | 'replay' | 'charts' | 'define';

const STORAGE_KEY = 'corner_sel_';

/* ── GPS Trace response shape ─────────────────────────── */

interface GpsTraceData {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds: number[];
}

export function CornersTab({ corners: rawCorners, sessionId }: CornersTabProps) {
  const corners = rawCorners ?? [];
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(corners.map((c) => c.corner_id)),
  );
  const [subTab, setSubTab] = useState<SubTab>('coaching');

  // Fetch GPS trace for the canvas track map + CornerDefiner
  const { data: gpsTrace } = useQuery({
    queryKey: ['gps-trace-corners', sessionId],
    queryFn: () => api.get<GpsTraceData>(`/sessions/${sessionId}/gps-trace`),
    staleTime: 5 * 60 * 1000,
  });

  // Fetch corner GPS positions for the canvas map
  const { data: posData } = useQuery({
    queryKey: ['corner-positions', sessionId],
    queryFn: () => api.get<{ corners: CornerPosition[] }>(`/sessions/${sessionId}/corner-positions`),
    enabled: !!sessionId,
    staleTime: 5 * 60 * 1000,
  });

  // Build TrackLayout for CornerPicker from GPS trace + corner positions
  const trackLayout = useMemo<TrackLayout | null>(() => {
    if (!gpsTrace?.latitudes?.length) return null;
    const positions = posData?.corners ?? [];
    const dists = gpsTrace.distances;

    // Interpolate lat/lon from GPS trace at a given distance
    const interpolateAt = (dist: number): { lat: number; lon: number } | null => {
      if (!dists?.length || dists.length !== gpsTrace.latitudes.length) return null;
      // Clamp to trace bounds
      if (dist <= dists[0]) return { lat: gpsTrace.latitudes[0], lon: gpsTrace.longitudes[0] };
      if (dist >= dists[dists.length - 1]) return { lat: gpsTrace.latitudes[dists.length - 1], lon: gpsTrace.longitudes[dists.length - 1] };
      // Binary search for bracketing indices
      let lo = 0, hi = dists.length - 1;
      while (lo < hi - 1) {
        const mid = (lo + hi) >> 1;
        if (dists[mid] <= dist) lo = mid; else hi = mid;
      }
      const span = dists[hi] - dists[lo];
      const t = span > 0 ? (dist - dists[lo]) / span : 0;
      return {
        lat: gpsTrace.latitudes[lo] + t * (gpsTrace.latitudes[hi] - gpsTrace.latitudes[lo]),
        lon: gpsTrace.longitudes[lo] + t * (gpsTrace.longitudes[hi] - gpsTrace.longitudes[lo]),
      };
    };

    return {
      latitudes: gpsTrace.latitudes,
      longitudes: gpsTrace.longitudes,
      distances: gpsTrace.distances,
      speeds: gpsTrace.speeds ?? [],
      corners: corners.map((c) => {
        const pos = positions.find((p) => p.corner_id === c.corner_id);
        const dist_m = c.s_apex ?? (c.s_start + c.s_end) / 2;
        // Use position data if available, otherwise interpolate from GPS trace
        let lat = pos?.lat ?? 0;
        let lon = pos?.lon ?? 0;
        if ((!lat || !lon) && dist_m != null) {
          const interp = interpolateAt(dist_m);
          if (interp) { lat = interp.lat; lon = interp.lon; }
        }
        return {
          corner_id: c.corner_id,
          direction: c.direction ?? '',
          lat,
          lon,
          dist_m,
          s_start: c.s_start ?? null,
          s_end: c.s_end ?? null,
          s_apex: c.s_apex ?? null,
        };
      }),
    };
  }, [gpsTrace, posData, corners]);

  // Persist selection
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`${STORAGE_KEY}${sessionId}`);
      if (raw) {
        const ids: number[] = JSON.parse(raw);
        if (Array.isArray(ids) && ids.length > 0) {
          setSelected(new Set(ids));
        }
      }
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    try {
      localStorage.setItem(`${STORAGE_KEY}${sessionId}`, JSON.stringify(Array.from(selected)));
    } catch { /* ignore */ }
  }, [selected, sessionId]);

  const toggle = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(
    () => setSelected(new Set(corners.map((c) => c.corner_id))),
    [corners],
  );
  const clearAll = useCallback(() => setSelected(new Set()), []);

  const filtered = useMemo(
    () => corners.filter((c) => selected.has(c.corner_id)),
    [corners, selected],
  );

  if (corners.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <p className="text-steel font-telemetry text-sm mb-2">
              No corners detected for this session.
            </p>
            <p className="text-steel/60 font-telemetry text-xs mb-4">
              Corner detection requires GPS data with sufficient curvature changes.
            </p>
            <button
              type="button"
              onClick={() => setSubTab('define')}
              className="px-4 py-2 border border-pit-orange/50 text-pit-orange text-xs font-telemetry
                rounded hover:bg-pit-orange/10 transition-colors"
            >
              Define Corners Manually
            </button>
          </div>
        </div>
        {subTab === 'define' && (
          <div className="space-y-3">
            <p className="text-xs text-steel font-body">
              Click on the track to place entry, apex, and exit points for each corner. Saved corners will be used in future coaching analysis.
            </p>
            {gpsTrace?.latitudes?.length ? (
              <CornerDefiner
                sessionId={sessionId}
                latitudes={gpsTrace.latitudes}
                longitudes={gpsTrace.longitudes}
                distances={gpsTrace.distances}
                onDone={() => window.location.reload()}
              />
            ) : (
              <div className="flex items-center justify-center py-12 text-steel/60 text-sm">
                Loading GPS trace data...
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Canvas track map — click corners/segments to toggle selection */}
      {trackLayout ? (
        <CornerPicker
          trackLayout={trackLayout}
          controlled
          selected={selected}
          onToggle={toggle}
          onSelectAll={selectAll}
          onClearAll={clearAll}
          height="320px"
        />
      ) : (
        <div className="flex items-center justify-center py-12 rounded-lg border border-steel/20 bg-concrete">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
            <span className="text-steel text-sm font-telemetry">Loading track map...</span>
          </div>
        </div>
      )}

      {/* Sub-tab navigation */}
      <div className="flex gap-1 border-b border-steel/10">
        {([
          { key: 'coaching' as SubTab, label: 'Corner Coaching' },
          { key: 'replay' as SubTab, label: 'Corner Replay' },
          { key: 'charts' as SubTab, label: 'Analysis Charts' },
          { key: 'define' as SubTab, label: 'Define Corners' },
        ]).map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setSubTab(tab.key)}
            className={`px-4 py-2 text-xs font-telemetry uppercase tracking-wider transition-colors relative ${
              subTab === tab.key
                ? 'text-acid-green'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {tab.label}
            {subTab === tab.key && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-acid-green" />
            )}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      {subTab === 'coaching' && (
        <CoachingTable corners={filtered} />
      )}

      {subTab === 'replay' && (
        <CornerReplay sessionId={sessionId} cornerIds={Array.from(selected)} />
      )}

      {subTab === 'charts' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <BrakePrecisionChart sessionId={sessionId} />
            <CornerMasteryCard sessionId={sessionId} />
            <ThrottleOnsetMap sessionId={sessionId} />
            <ConsistencyHeatmap sessionId={sessionId} />
          </div>
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Corner Lateral G Distribution</h3>
            <CornerGHistogram sessionId={sessionId} corners={corners} />
          </div>
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Corner Apex Speed Trend</h3>
            <p className="text-xs text-steel mb-3 font-body">Minimum speed per corner across laps — shows learning and consistency</p>
            <CornerSpeedTrend sessionId={sessionId} />
          </div>
        </div>
      )}

      {subTab === 'define' && (
        <div className="space-y-3">
          <p className="text-xs text-steel font-body">
            Click on the track to place entry, apex, and exit points for each corner. Saved corners will be used in future coaching analysis.
          </p>
          {gpsTrace?.latitudes?.length ? (
            <CornerDefiner
              sessionId={sessionId}
              latitudes={gpsTrace.latitudes}
              longitudes={gpsTrace.longitudes}
              distances={gpsTrace.distances}
              onDone={() => {
                // Switch back to coaching tab after defining corners
                setSubTab('coaching');
                // Reload page to pick up new coaching data
                window.location.reload();
              }}
            />
          ) : (
            <div className="flex items-center justify-center py-12 text-steel/60 text-sm">
              Loading GPS trace data...
            </div>
          )}
        </div>
      )}
    </div>
  );
}
