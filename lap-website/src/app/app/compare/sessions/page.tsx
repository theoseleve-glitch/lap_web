'use client';

import { useState, useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ── Types ──────────────────────────────────────────────── */

interface SessionPickerItem {
  session_id: string;
  driver_name: string;
  track_name: string;
  session_date: string;
  session_type: string | null;
  n_laps: number;
  best_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
}

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  is_valid: boolean | number;
}

interface SessionData {
  session_id: string;
  driver_name: string;
  track_name: string;
  session_date: string;
  session_type: string;
  n_laps: number;
  best_lap_time_s: number | null;
  mean_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
  laps: LapData[];
  scores?: {
    pace_score: number | null;
    consistency_score: number | null;
    execution_score: number | null;
    robustness_score: number | null;
  };
}

interface CompareResponse {
  session_a: SessionData;
  session_b: SessionData;
}

interface SessionListResponse {
  sessions: SessionPickerItem[];
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreTier(s: number | null): { color: string; label: string } {
  if (s == null) return { color: 'text-steel', label: '—' };
  if (s >= 80) return { color: 'text-acid-green', label: s.toFixed(1) };
  if (s >= 60) return { color: 'text-marshal-yellow', label: s.toFixed(1) };
  if (s >= 40) return { color: 'text-pit-orange', label: s.toFixed(1) };
  return { color: 'text-safety-red', label: s.toFixed(1) };
}

const COLOR_A = '#B6FF2E'; // acid-green
const COLOR_B = '#FF6A00'; // pit-orange

/* ── Score Bar ──────────────────────────────────────────── */

function ScoreBar({ label, valA, valB, max }: { label: string; valA: number | null; valB: number | null; max: number }) {
  const pctA = valA != null ? (valA / max) * 100 : 0;
  const pctB = valB != null ? (valB / max) * 100 : 0;
  const diff = valA != null && valB != null ? valB - valA : null;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-steel font-telemetry text-xs uppercase tracking-wider">{label}</span>
        {diff != null && (
          <span className={`font-telemetry text-[10px] ${diff > 0.1 ? 'text-pit-orange' : diff < -0.1 ? 'text-acid-green' : 'text-steel/40'}`}>
            {diff > 0 ? `B +${diff.toFixed(1)}` : diff < 0 ? `A +${Math.abs(diff).toFixed(1)}` : 'Even'}
          </span>
        )}
      </div>
      {/* Bar A */}
      <div className="flex items-center gap-2">
        <span className="text-acid-green font-telemetry text-[10px] w-8 text-right">{valA?.toFixed(1) ?? '—'}</span>
        <div className="flex-1 h-2 bg-steel/10 rounded-full overflow-hidden">
          <div className="h-full bg-acid-green/70 rounded-full transition-all" style={{ width: `${pctA}%` }} />
        </div>
      </div>
      {/* Bar B */}
      <div className="flex items-center gap-2">
        <span className="text-pit-orange font-telemetry text-[10px] w-8 text-right">{valB?.toFixed(1) ?? '—'}</span>
        <div className="flex-1 h-2 bg-steel/10 rounded-full overflow-hidden">
          <div className="h-full bg-pit-orange/70 rounded-full transition-all" style={{ width: `${pctB}%` }} />
        </div>
      </div>
    </div>
  );
}

/* ── Lap Overlay Chart ──────────────────────────────────── */

const PAD = { top: 15, right: 15, bottom: 30, left: 55 };

function LapOverlayChart({ a, b }: { a: SessionData; b: SessionData }) {
  const lapsA = useMemo(() => a.laps.filter((l) => l.lap_time_s != null), [a]);
  const lapsB = useMemo(() => b.laps.filter((l) => l.lap_time_s != null), [b]);

  const { minTime, maxTime, timeRange, maxLap } = useMemo(() => {
    const allTimes = [...lapsA, ...lapsB].map((l) => l.lap_time_s!);
    if (allTimes.length === 0) return { minTime: 0, maxTime: 1, timeRange: 1, maxLap: 1 };
    const mn = Math.min(...allTimes);
    const mx = Math.max(...allTimes);
    return {
      minTime: mn,
      maxTime: mx,
      timeRange: mx - mn || 1,
      maxLap: Math.max(lapsA.length, lapsB.length),
    };
  }, [lapsA, lapsB]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + plotW, y);
        ctx.stroke();
      }

      // Y-axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const val = maxTime - (i / 4) * timeRange;
        const m = Math.floor(val / 60);
        const s = (val % 60).toFixed(1);
        ctx.fillText(`${m}:${s.padStart(4, '0')}`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }

      // X-axis labels
      ctx.textAlign = 'center';
      const step = Math.max(1, Math.floor(maxLap / 8));
      for (let i = 1; i <= maxLap; i += step) {
        const x = PAD.left + ((i - 1) / (maxLap - 1 || 1)) * plotW;
        ctx.fillText(`L${i}`, x, h - 8);
      }

      // Hover line
      const hoveredLap = hover ? Math.round(hover.nx * (maxLap - 1)) : -1;
      if (hover && hoveredLap >= 0) {
        const hx = PAD.left + (hoveredLap / (maxLap - 1 || 1)) * plotW;
        ctx.strokeStyle = 'rgba(243, 240, 232, 0.2)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hx, PAD.top);
        ctx.lineTo(hx, PAD.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Helper to draw a line series
      const drawLine = (laps: LapData[], color: string, hovered: boolean) => {
        if (laps.length < 2) return;
        ctx.strokeStyle = hovered ? color : color + '99';
        ctx.lineWidth = hovered ? 2.5 : 1.5;
        ctx.beginPath();
        for (let i = 0; i < laps.length; i++) {
          const x = PAD.left + (i / (maxLap - 1 || 1)) * plotW;
          const y = PAD.top + plotH - ((laps[i].lap_time_s! - minTime) / timeRange) * plotH;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Points
        for (let i = 0; i < laps.length; i++) {
          const x = PAD.left + (i / (maxLap - 1 || 1)) * plotW;
          const y = PAD.top + plotH - ((laps[i].lap_time_s! - minTime) / timeRange) * plotH;
          const isLapHovered = i === hoveredLap;
          ctx.beginPath();
          ctx.arc(x, y, isLapHovered ? 4 : 2, 0, Math.PI * 2);
          ctx.fillStyle = isLapHovered ? color : color + 'AA';
          ctx.fill();
        }
      };

      drawLine(lapsA, COLOR_A, true);
      drawLine(lapsB, COLOR_B, true);

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = COLOR_A;
      ctx.fillRect(PAD.left + 5, PAD.top + 3, 12, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText(`A: ${a.driver_name}`, PAD.left + 22, PAD.top + 7);
      ctx.fillStyle = COLOR_B;
      ctx.fillRect(PAD.left + 5, PAD.top + 14, 12, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText(`B: ${b.driver_name}`, PAD.left + 22, PAD.top + 18);
    },
    [lapsA, lapsB, minTime, maxTime, timeRange, maxLap, a.driver_name, b.driver_name],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const lap = Math.round(hover.nx * (maxLap - 1));
      if (lap < 0) return null;
      const lapA = lapsA[lap];
      const lapB = lapsB[lap];
      if (!lapA && !lapB) return null;

      const lines: TooltipData['lines'] = [{ label: 'Lap', value: String(lap + 1) }];
      if (lapA) lines.push({ label: `A`, value: fmtTime(lapA.lap_time_s), color: COLOR_A });
      if (lapB) lines.push({ label: `B`, value: fmtTime(lapB.lap_time_s), color: COLOR_B });
      if (lapA?.lap_time_s != null && lapB?.lap_time_s != null) {
        const delta = lapB.lap_time_s - lapA.lap_time_s;
        lines.push({
          label: 'Delta',
          value: `${delta > 0 ? '+' : ''}${delta.toFixed(3)}s`,
          color: delta > 0 ? COLOR_A : COLOR_B,
        });
      }
      return { header: `Lap ${lap + 1}`, lines };
    },
    [lapsA, lapsB, maxLap],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [lapsA, lapsB],
    padding: PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-64" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

export default function CompareSessionsPage() {
  const [sessionA, setSessionA] = useState('');
  const [sessionB, setSessionB] = useState('');
  const [searchA, setSearchA] = useState('');
  const [searchB, setSearchB] = useState('');

  const { data: sessionList } = useQuery({
    queryKey: ['sessions-list'],
    queryFn: () => api.get<SessionListResponse>('/sessions'),
  });

  const sessions = sessionList?.sessions ?? [];

  const filteredA = useMemo(
    () =>
      sessions.filter((s) => {
        const hay = `${s.driver_name} ${s.track_name} ${s.session_date}`.toLowerCase();
        return hay.includes(searchA.toLowerCase());
      }),
    [sessions, searchA],
  );
  const filteredB = useMemo(
    () =>
      sessions.filter((s) => {
        const hay = `${s.driver_name} ${s.track_name} ${s.session_date}`.toLowerCase();
        return hay.includes(searchB.toLowerCase());
      }),
    [sessions, searchB],
  );

  const canCompare = sessionA !== '' && sessionB !== '' && sessionA !== sessionB;

  const { data: comparison, isLoading: comparing } = useQuery({
    queryKey: ['compare-sessions', sessionA, sessionB],
    queryFn: () => api.get<CompareResponse>(`/compare/sessions?a=${sessionA}&b=${sessionB}`),
    enabled: canCompare,
  });

  const sa = comparison?.session_a;
  const sb = comparison?.session_b;

  function pickerLabel(s: SessionPickerItem): string {
    return `${s.session_date} — ${s.driver_name} @ ${s.track_name ?? 'Unknown'} (${s.n_laps}L)`;
  }

  return (
    <div>
      <PageHeader
        title="Compare Sessions"
        subtitle="Side-by-side lap times, scores, and driving style"
      />

      {/* ── Session Pickers ────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Picker A */}
        <div className="bg-concrete rounded-lg border border-acid-green/20 p-4">
          <label className="block text-acid-green font-telemetry text-xs uppercase tracking-wider mb-2">
            Session A
          </label>
          <input
            type="text"
            placeholder="Search by driver, track, date..."
            value={searchA}
            onChange={(e) => setSearchA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-acid-green focus:ring-1 focus:ring-acid-green/30
              transition-colors mb-2"
          />
          <select
            value={sessionA}
            onChange={(e) => setSessionA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              focus:outline-none focus:border-acid-green transition-colors"
          >
            <option value="">Select session...</option>
            {filteredA.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {pickerLabel(s)}
              </option>
            ))}
          </select>
        </div>

        {/* Picker B */}
        <div className="bg-concrete rounded-lg border border-pit-orange/20 p-4">
          <label className="block text-pit-orange font-telemetry text-xs uppercase tracking-wider mb-2">
            Session B
          </label>
          <input
            type="text"
            placeholder="Search by driver, track, date..."
            value={searchB}
            onChange={(e) => setSearchB(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/30
              transition-colors mb-2"
          />
          <select
            value={sessionB}
            onChange={(e) => setSessionB(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              focus:outline-none focus:border-pit-orange transition-colors"
          >
            <option value="">Select session...</option>
            {filteredB.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {pickerLabel(s)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Loading ────────────────────────────────────── */}
      {comparing && (
        <div className="flex items-center justify-center h-32">
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      )}

      {/* ── Comparison Results ──────────────────────────── */}
      {sa && sb && (
        <>
          {/* Session header cards */}
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="bg-concrete rounded-lg border border-acid-green/30 p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="font-monument text-sm text-acid-green">A</span>
                {sa.grade && (
                  <span className={`font-monument text-lg ${scoreTier(sa.total_score).color}`}>{sa.grade}</span>
                )}
              </div>
              <p className="text-chalk font-body text-sm">{sa.track_name}</p>
              <p className="text-steel font-telemetry text-xs">
                {sa.driver_name} &middot; {sa.session_date} &middot; {sa.n_laps} laps
              </p>
              <div className="flex items-center gap-4 mt-2">
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">BEST</span>
                  <span className="text-acid-green font-telemetry text-sm">{fmtTime(sa.best_lap_time_s)}</span>
                </div>
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">MEAN</span>
                  <span className="text-steel font-telemetry text-sm">{fmtTime(sa.mean_lap_time_s)}</span>
                </div>
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">SCORE</span>
                  <span className={`font-telemetry text-sm ${scoreTier(sa.total_score).color}`}>
                    {scoreTier(sa.total_score).label}
                  </span>
                </div>
              </div>
            </div>

            <div className="bg-concrete rounded-lg border border-pit-orange/30 p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="font-monument text-sm text-pit-orange">B</span>
                {sb.grade && (
                  <span className={`font-monument text-lg ${scoreTier(sb.total_score).color}`}>{sb.grade}</span>
                )}
              </div>
              <p className="text-chalk font-body text-sm">{sb.track_name}</p>
              <p className="text-steel font-telemetry text-xs">
                {sb.driver_name} &middot; {sb.session_date} &middot; {sb.n_laps} laps
              </p>
              <div className="flex items-center gap-4 mt-2">
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">BEST</span>
                  <span className="text-pit-orange font-telemetry text-sm">{fmtTime(sb.best_lap_time_s)}</span>
                </div>
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">MEAN</span>
                  <span className="text-steel font-telemetry text-sm">{fmtTime(sb.mean_lap_time_s)}</span>
                </div>
                <div>
                  <span className="text-steel/60 text-[10px] font-telemetry block">SCORE</span>
                  <span className={`font-telemetry text-sm ${scoreTier(sb.total_score).color}`}>
                    {scoreTier(sb.total_score).label}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* ── Lap Time Overlay Chart ──────────────────── */}
          <ChartPanel
            title="Lap Time Overlay"
            subtitle="Hover to compare individual laps"
          >
            <LapOverlayChart a={sa} b={sb} />
          </ChartPanel>

          {/* ── Score Breakdown ─────────────────────────── */}
          <div className="mt-6">
            <h2 className="font-body text-chalk text-lg mb-4">Score Breakdown</h2>
            <div className="bg-concrete rounded-lg border border-steel/20 p-5 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5">
              <ScoreBar
                label="Total Score"
                valA={sa.total_score}
                valB={sb.total_score}
                max={100}
              />
              <ScoreBar
                label="Pace"
                valA={sa.scores?.pace_score ?? null}
                valB={sb.scores?.pace_score ?? null}
                max={25}
              />
              <ScoreBar
                label="Consistency"
                valA={sa.scores?.consistency_score ?? null}
                valB={sb.scores?.consistency_score ?? null}
                max={25}
              />
              <ScoreBar
                label="Execution"
                valA={sa.scores?.execution_score ?? null}
                valB={sb.scores?.execution_score ?? null}
                max={25}
              />
              <ScoreBar
                label="Robustness"
                valA={sa.scores?.robustness_score ?? null}
                valB={sb.scores?.robustness_score ?? null}
                max={25}
              />
            </div>
          </div>

          {/* ── Delta Summary ──────────────────────────── */}
          {sa.best_lap_time_s != null && sb.best_lap_time_s != null && (
            <div className="mt-6">
              <h2 className="font-body text-chalk text-lg mb-4">Delta Summary</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <DeltaCard
                  label="Best Lap Delta"
                  delta={sb.best_lap_time_s - sa.best_lap_time_s}
                  format="time"
                  lowerIsBetter
                />
                {sa.mean_lap_time_s != null && sb.mean_lap_time_s != null && (
                  <DeltaCard
                    label="Mean Lap Delta"
                    delta={sb.mean_lap_time_s - sa.mean_lap_time_s}
                    format="time"
                    lowerIsBetter
                  />
                )}
                {sa.total_score != null && sb.total_score != null && (
                  <DeltaCard
                    label="Score Delta"
                    delta={sb.total_score - sa.total_score}
                    format="score"
                  />
                )}
                <DeltaCard
                  label="Lap Count Delta"
                  delta={sb.n_laps - sa.n_laps}
                  format="integer"
                />
              </div>
            </div>
          )}

          {/* ── Lap-by-Lap Table ──────────────────────── */}
          <div className="mt-6">
            <h2 className="font-body text-chalk text-lg mb-4">Lap-by-Lap Comparison</h2>
            <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-steel/20">
                      <th className="text-left px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Lap</th>
                      <th className="text-left px-4 py-3 text-acid-green font-telemetry text-xs uppercase tracking-wider">Time A</th>
                      <th className="text-left px-4 py-3 text-pit-orange font-telemetry text-xs uppercase tracking-wider">Time B</th>
                      <th className="text-right px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Delta</th>
                      <th className="text-center px-4 py-3 text-steel font-telemetry text-xs uppercase tracking-wider">Faster</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: Math.max(sa.laps.length, sb.laps.length) }, (_, i) => {
                      const la = sa.laps[i];
                      const lb = sb.laps[i];
                      const tA = la?.lap_time_s;
                      const tB = lb?.lap_time_s;
                      const delta = tA != null && tB != null ? tB - tA : null;
                      const faster = delta != null ? (delta > 0.001 ? 'A' : delta < -0.001 ? 'B' : '=') : null;

                      return (
                        <tr key={i} className="border-b border-steel/10 hover:bg-asphalt/30 transition-colors">
                          <td className="px-4 py-2 text-chalk font-telemetry text-sm">{i + 1}</td>
                          <td className={`px-4 py-2 font-telemetry text-sm ${faster === 'A' ? 'text-acid-green' : 'text-chalk/70'}`}>
                            {fmtTime(tA)}
                          </td>
                          <td className={`px-4 py-2 font-telemetry text-sm ${faster === 'B' ? 'text-pit-orange' : 'text-chalk/70'}`}>
                            {fmtTime(tB)}
                          </td>
                          <td className="px-4 py-2 text-right font-telemetry text-sm">
                            {delta != null ? (
                              <span className={faster === 'A' ? 'text-acid-green' : faster === 'B' ? 'text-pit-orange' : 'text-steel/40'}>
                                {delta > 0 ? '+' : ''}{delta.toFixed(3)}s
                              </span>
                            ) : (
                              <span className="text-steel/30">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-center">
                            {faster === 'A' && <span className="inline-block w-5 h-5 rounded-full bg-acid-green/20 text-acid-green text-[10px] font-monument leading-5">A</span>}
                            {faster === 'B' && <span className="inline-block w-5 h-5 rounded-full bg-pit-orange/20 text-pit-orange text-[10px] font-monument leading-5">B</span>}
                            {faster === '=' && <span className="text-steel/30 text-[10px] font-telemetry">=</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ── Prompt State ───────────────────────────────── */}
      {!canCompare && !comparing && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <div className="text-4xl mb-3">⇄</div>
          <h3 className="font-monument text-lg text-chalk mb-2">Select Two Sessions</h3>
          <p className="text-steel font-body text-sm max-w-md mx-auto">
            Pick two different sessions above to see a side-by-side breakdown of lap times,
            scores, and driving performance.
          </p>
        </div>
      )}
    </div>
  );
}

/* ── Delta Card ─────────────────────────────────────────── */

function DeltaCard({ label, delta, format, lowerIsBetter = false }: {
  label: string;
  delta: number;
  format: 'time' | 'score' | 'integer';
  lowerIsBetter?: boolean;
}) {
  const aWins = lowerIsBetter ? delta > 0 : delta < 0;
  const bWins = lowerIsBetter ? delta < 0 : delta > 0;
  const even = Math.abs(delta) < 0.001;

  let display: string;
  if (format === 'time') display = `${delta > 0 ? '+' : ''}${delta.toFixed(3)}s`;
  else if (format === 'score') display = `${delta > 0 ? '+' : ''}${delta.toFixed(1)}`;
  else display = `${delta > 0 ? '+' : ''}${delta}`;

  return (
    <div className="bg-concrete rounded-lg border border-steel/20 p-4">
      <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">{label}</p>
      <p className={`font-monument text-2xl ${even ? 'text-steel/40' : aWins ? 'text-acid-green' : bWins ? 'text-pit-orange' : 'text-steel'}`}>
        {even ? '0.000' : display}
      </p>
      {!even && (
        <p className={`font-telemetry text-[10px] mt-0.5 ${aWins ? 'text-acid-green' : 'text-pit-orange'}`}>
          {aWins ? 'A is better' : 'B is better'}
        </p>
      )}
    </div>
  );
}
