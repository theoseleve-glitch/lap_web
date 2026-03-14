'use client';

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { CoachingTable } from './CoachingTable';
import { CornerReplay } from '../corner-replay';
import { BrakePrecisionChart } from './BrakePrecisionChart';
import { CornerMasteryCard } from './CornerMasteryCard';
import { ThrottleOnsetMap } from './ThrottleOnsetMap';
import { ConsistencyHeatmap } from './ConsistencyHeatmap';
import { CornerGHistogram } from './CornerGHistogram';
import { CornerSpeedTrend } from './CornerSpeedTrend';
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

type SubTab = 'coaching' | 'replay' | 'charts' | 'ocp';

/* ── OCP response types ─────────────────────────────── */

interface OCPLapResult {
  lap_number: number;
  is_best: boolean;
  actual_time_s: number;
  optimal_time_s: number;
  delta_s: number;
  delta_ms: number;
  actual_apex_mps: number | null;
  ocp_apex_mps: number;
  converged: boolean;
  v_entry: number;
  v_exit: number;
}

interface OCPCornerResult {
  corner_id: number;
  s_start: number;
  s_end: number;
  direction: string | null;
  laps: OCPLapResult[];
}

interface OCPFullLap {
  lap_time_s: number | null;
  converged: boolean;
  source: string;
  message?: string;
}

interface OCPResponse {
  corner_results: OCPCornerResult[];
  full_lap_ocp: OCPFullLap | null;
  best_lap: number;
}

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

  // OCP mutation — runs segment solver for selected corners across all laps
  const ocpMutation = useMutation({
    mutationFn: (cornerIds: number[]) =>
      api.post<OCPResponse>(`/sessions/${sessionId}/ocp-corner`, { corner_ids: cornerIds }),
  });

  // Fetch GPS trace for the canvas track map
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
          </div>
        </div>
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
          { key: 'ocp' as SubTab, label: 'OCP Optimal' },
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

      {subTab === 'ocp' && (
        <div className="space-y-4">
          {/* Solve button */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={selected.size === 0 || ocpMutation.isPending}
              onClick={() => ocpMutation.mutate(Array.from(selected))}
              className="px-4 py-2 bg-acid-green/20 text-acid-green border border-acid-green/30 rounded-lg text-xs font-telemetry uppercase tracking-wider hover:bg-acid-green/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {ocpMutation.isPending ? (
                <span className="flex items-center gap-2">
                  <span className="w-3 h-3 border-2 border-acid-green/30 border-t-acid-green rounded-full animate-spin" />
                  Solving...
                </span>
              ) : (
                `Solve OCP for ${selected.size} corner${selected.size !== 1 ? 's' : ''}`
              )}
            </button>
            <span className="text-steel/60 text-xs font-telemetry">
              Runs optimal control solver on selected corners across all laps
            </span>
          </div>

          {ocpMutation.isError && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              <p className="text-red-400 text-xs font-telemetry">
                {(ocpMutation.error as Error)?.message || 'OCP solve failed'}
              </p>
            </div>
          )}

          {ocpMutation.data && (
            <div className="space-y-4">
              {/* Full-lap OCP summary */}
              {ocpMutation.data.full_lap_ocp && (
                <div className="bg-concrete rounded-xl border border-steel/10 p-4">
                  <h3 className="text-sm font-monument text-chalk mb-2">Full-Lap Optimal</h3>
                  {ocpMutation.data.full_lap_ocp.lap_time_s != null ? (
                    <div className="flex items-baseline gap-3">
                      <span className="text-2xl font-monument text-acid-green">
                        {ocpMutation.data.full_lap_ocp.lap_time_s.toFixed(3)}s
                      </span>
                      <span className="text-xs text-steel font-telemetry">
                        optimal lap time (best lap #{ocpMutation.data.best_lap})
                      </span>
                      {ocpMutation.data.full_lap_ocp.converged && (
                        <span className="text-[10px] text-acid-green/70 font-telemetry uppercase">converged</span>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-steel/60 font-telemetry">
                      {ocpMutation.data.full_lap_ocp.message || 'Full-lap OCP pending — computed on upload'}
                    </p>
                  )}
                </div>
              )}

              {/* Per-corner results */}
              {ocpMutation.data.corner_results.map((cr) => (
                <div key={cr.corner_id} className="bg-concrete rounded-xl border border-steel/10 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="w-6 h-6 rounded-full bg-acid-green/20 text-acid-green flex items-center justify-center text-xs font-monument">
                      {cr.corner_id}
                    </span>
                    <h3 className="text-sm font-monument text-chalk">
                      Corner {cr.corner_id}
                      {cr.direction && <span className="text-steel ml-1">({cr.direction})</span>}
                    </h3>
                    <span className="text-[10px] text-steel/50 font-telemetry ml-auto">
                      {(cr.s_end - cr.s_start).toFixed(0)}m segment
                    </span>
                  </div>

                  {cr.laps.length === 0 ? (
                    <p className="text-xs text-steel/60 font-telemetry">No valid laps for this corner</p>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs font-telemetry">
                        <thead>
                          <tr className="text-steel/70 border-b border-steel/10">
                            <th className="text-left py-1.5 pr-3">Lap</th>
                            <th className="text-right py-1.5 px-2">Actual</th>
                            <th className="text-right py-1.5 px-2">Optimal</th>
                            <th className="text-right py-1.5 px-2">Delta</th>
                            <th className="text-right py-1.5 px-2">Apex (act)</th>
                            <th className="text-right py-1.5 px-2">Apex (opt)</th>
                            <th className="text-right py-1.5 px-2">Entry</th>
                            <th className="text-right py-1.5 pl-2">Exit</th>
                          </tr>
                        </thead>
                        <tbody>
                          {cr.laps.map((lap) => {
                            const deltaColor = lap.delta_ms > 100 ? 'text-red-400' :
                              lap.delta_ms > 30 ? 'text-amber-400' : 'text-acid-green';
                            return (
                              <tr key={lap.lap_number} className={`border-b border-steel/5 ${lap.is_best ? 'bg-acid-green/5' : ''}`}>
                                <td className="py-1.5 pr-3 text-chalk">
                                  {lap.lap_number}
                                  {lap.is_best && <span className="ml-1 text-acid-green text-[10px]">BEST</span>}
                                </td>
                                <td className="text-right py-1.5 px-2 text-chalk">{lap.actual_time_s.toFixed(3)}s</td>
                                <td className="text-right py-1.5 px-2 text-acid-green">{lap.optimal_time_s.toFixed(3)}s</td>
                                <td className={`text-right py-1.5 px-2 ${deltaColor}`}>
                                  +{lap.delta_ms.toFixed(0)}ms
                                </td>
                                <td className="text-right py-1.5 px-2 text-steel">
                                  {lap.actual_apex_mps != null ? `${(lap.actual_apex_mps * 3.6).toFixed(1)}` : '—'}
                                </td>
                                <td className="text-right py-1.5 px-2 text-steel">
                                  {(lap.ocp_apex_mps * 3.6).toFixed(1)}
                                </td>
                                <td className="text-right py-1.5 px-2 text-steel/60">
                                  {(lap.v_entry * 3.6).toFixed(1)}
                                </td>
                                <td className="text-right py-1.5 pl-2 text-steel/60">
                                  {(lap.v_exit * 3.6).toFixed(1)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      <p className="text-[10px] text-steel/40 mt-1 font-telemetry">Speeds in km/h</p>
                    </div>
                  )}
                </div>
              ))}

              {ocpMutation.data.corner_results.length === 0 && (
                <div className="text-center py-8">
                  <p className="text-steel text-sm font-telemetry">No corner results returned</p>
                  <p className="text-steel/60 text-xs font-telemetry mt-1">
                    Selected corners may lack sufficient GPS data or curvature
                  </p>
                </div>
              )}
            </div>
          )}

          {!ocpMutation.data && !ocpMutation.isPending && !ocpMutation.isError && (
            <div className="text-center py-8">
              <p className="text-steel text-sm font-telemetry">
                Select corners on the map above, then click Solve OCP
              </p>
              <p className="text-steel/60 text-xs font-telemetry mt-1">
                The solver computes the physically optimal time through each corner using nonlinear optimization (CasADi/IPOPT)
              </p>
            </div>
          )}
        </div>
      )}

    </div>
  );
}
