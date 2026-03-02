'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api-client';
import { CompareChartPanel } from '@/components/app/compare';

// ── Types ────────────────────────────────────────────────────────

interface SessionListItem {
  session_id: string;
  csv_filename: string;
  driver_name: string;
  track_name: string | null;
  session_date: string;
  n_laps: number | null;
  total_score: number | null;
  grade: string | null;
}

interface SessionDetail {
  session_id: string;
  csv_filename: string;
  driver_name: string;
  track_name: string | null;
  session_date: string;
  session_type: string;
  track_state: string;
  n_laps: number | null;
  best_lap_time_s: number | null;
  mean_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
}

interface ScoreData {
  pace_score: number | null;
  pace_max: number | null;
  consistency_score: number | null;
  consistency_max: number | null;
  execution_score: number | null;
  execution_max: number | null;
  robustness_score: number | null;
  robustness_max: number | null;
  adaptation_score: number | null;
}

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  speed_mean_mps: number | null;
  speed_max_mps: number | null;
  is_valid: number;
  is_best: number;
}

interface ComparisonData {
  session_a: {
    session: SessionDetail;
    scores: ScoreData | null;
    laps: LapData[];
  };
  session_b: {
    session: SessionDetail;
    scores: ScoreData | null;
    laps: LapData[];
  };
}

// ── Helpers ──────────────────────────────────────────────────────

function formatLapTime(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return '--';
  if (seconds >= 60) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds - mins * 60;
    return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
  }
  return `${seconds.toFixed(3)}s`;
}

function mpsToKmh(mps: number | null | undefined): string {
  if (mps == null || !isFinite(mps)) return '--';
  return (mps * 3.6).toFixed(1);
}

const GRADE_COLORS: Record<string, string> = {
  S: 'text-yellow-400',
  A: 'text-green-400',
  B: 'text-cyan-400',
  C: 'text-yellow-500',
  D: 'text-orange-400',
  F: 'text-red-500',
};

function gradeColor(grade: string | null): string {
  if (!grade) return 'text-steel';
  return GRADE_COLORS[grade.charAt(0).toUpperCase()] || 'text-steel';
}

/** Returns "text-green-400" if positive delta is better, "text-red-400" if worse. */
function deltaColor(delta: number, lowerIsBetter = false): string {
  if (delta === 0) return 'text-steel';
  if (lowerIsBetter) {
    return delta < 0 ? 'text-green-400' : 'text-red-400';
  }
  return delta > 0 ? 'text-green-400' : 'text-red-400';
}

function formatDelta(delta: number | null, decimals = 1): string {
  if (delta == null || !isFinite(delta)) return '--';
  const sign = delta > 0 ? '+' : '';
  return `${sign}${delta.toFixed(decimals)}`;
}

// ── Session Selector Dropdown ───────────────────────────────────

function SessionSelector({
  label,
  sessions,
  selectedId,
  onChange,
  accentColor,
}: {
  label: string;
  sessions: SessionListItem[];
  selectedId: string;
  onChange: (id: string) => void;
  accentColor: string;
}) {
  return (
    <div className="flex-1">
      <label className="block text-xs font-monument uppercase tracking-wider mb-2" style={{ color: accentColor }}>
        {label}
      </label>
      <select
        value={selectedId}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
          focus:outline-none focus:ring-1 appearance-none cursor-pointer"
        style={{
          borderColor: selectedId ? accentColor + '40' : undefined,
          // @ts-expect-error -- focus ring color
          '--tw-ring-color': accentColor + '50',
        }}
      >
        <option value="">Select a session...</option>
        {sessions.map((s) => (
          <option key={s.session_id} value={s.session_id}>
            {s.driver_name} - {s.track_name || 'Unknown'} ({s.session_date})
            {s.total_score != null ? ` [${s.total_score.toFixed(0)}]` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

// ── Score Comparison Card ───────────────────────────────────────

function ScoreCompareCard({
  label,
  scoreA,
  scoreB,
  max,
  colorA,
  colorB,
}: {
  label: string;
  scoreA: number | null;
  scoreB: number | null;
  max: number;
  colorA: string;
  colorB: string;
}) {
  const pctA = scoreA != null ? Math.min((scoreA / max) * 100, 100) : 0;
  const pctB = scoreB != null ? Math.min((scoreB / max) * 100, 100) : 0;
  const delta = scoreA != null && scoreB != null ? scoreA - scoreB : null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-monument text-chalk">{label}</h4>
        {delta != null && (
          <span className={`text-xs font-telemetry ${deltaColor(delta)}`}>
            A {formatDelta(delta)}
          </span>
        )}
      </div>

      {/* Session A bar */}
      <div className="mb-2">
        <div className="flex justify-between text-xs mb-1">
          <span className="font-body" style={{ color: colorA }}>Session A</span>
          <span className="font-telemetry text-chalk">
            {scoreA != null ? scoreA.toFixed(1) : '--'} / {max}
          </span>
        </div>
        <div className="w-full h-2 bg-asphalt rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pctA}%`, backgroundColor: colorA }}
          />
        </div>
      </div>

      {/* Session B bar */}
      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="font-body" style={{ color: colorB }}>Session B</span>
          <span className="font-telemetry text-chalk">
            {scoreB != null ? scoreB.toFixed(1) : '--'} / {max}
          </span>
        </div>
        <div className="w-full h-2 bg-asphalt rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pctB}%`, backgroundColor: colorB }}
          />
        </div>
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────

const COLOR_A = '#3ddc84'; // acid-green
const COLOR_B = '#ff8c00'; // pit-orange

export default function CompareSessionsPage() {
  const searchParams = useSearchParams();

  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);

  const [sessionAId, setSessionAId] = useState('');
  const [sessionBId, setSessionBId] = useState('');

  const [comparison, setComparison] = useState<ComparisonData | null>(null);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [compError, setCompError] = useState<string | null>(null);

  // Pre-populate from URL search params (?a=...&b=...)
  useEffect(() => {
    const paramA = searchParams.get('a');
    const paramB = searchParams.get('b');
    if (paramA) setSessionAId(paramA);
    if (paramB) setSessionBId(paramB);
  }, [searchParams]);

  // Fetch sessions list
  useEffect(() => {
    let cancelled = false;

    async function fetchSessions() {
      setLoadingSessions(true);
      try {
        const res = await api.get<{ sessions: SessionListItem[] }>('/sessions?limit=100');
        if (!cancelled) {
          setSessions(res.sessions || []);
        }
      } catch {
        // Non-critical — show empty list
      } finally {
        if (!cancelled) setLoadingSessions(false);
      }
    }

    fetchSessions();
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch comparison when both selected
  useEffect(() => {
    if (!sessionAId || !sessionBId) {
      setComparison(null);
      setCompError(null);
      return;
    }

    let cancelled = false;

    async function fetchComparison() {
      setLoadingComparison(true);
      setCompError(null);

      try {
        const res = await api.get<ComparisonData>(
          `/compare/sessions?a=${encodeURIComponent(sessionAId)}&b=${encodeURIComponent(sessionBId)}`,
        );
        if (!cancelled) {
          setComparison(res);
        }
      } catch (err) {
        if (!cancelled) {
          setCompError(err instanceof Error ? err.message : 'Failed to load comparison');
        }
      } finally {
        if (!cancelled) setLoadingComparison(false);
      }
    }

    fetchComparison();
    return () => {
      cancelled = true;
    };
  }, [sessionAId, sessionBId]);

  const swapSessions = useCallback(() => {
    const oldA = sessionAId;
    const oldB = sessionBId;
    setSessionAId(oldB);
    setSessionBId(oldA);
  }, [sessionAId, sessionBId]);

  // ── Derived comparison stats ──────────────────────────────────

  const compStats = useMemo(() => {
    if (!comparison) return null;

    const a = comparison.session_a;
    const b = comparison.session_b;

    const totalDelta =
      a.session.total_score != null && b.session.total_score != null
        ? a.session.total_score - b.session.total_score
        : null;

    const bestLapDelta =
      a.session.best_lap_time_s != null && b.session.best_lap_time_s != null
        ? a.session.best_lap_time_s - b.session.best_lap_time_s
        : null;

    const avgLapDelta =
      a.session.mean_lap_time_s != null && b.session.mean_lap_time_s != null
        ? a.session.mean_lap_time_s - b.session.mean_lap_time_s
        : null;

    return { totalDelta, bestLapDelta, avgLapDelta };
  }, [comparison]);

  // ── Render ────────────────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-monument text-chalk tracking-tight">Compare Sessions</h1>
        <p className="text-steel text-sm font-body mt-1">
          Select two sessions to compare scores, lap times, and performance metrics side by side.
        </p>
      </div>

      {/* Session selectors */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-5 mb-6">
        {loadingSessions ? (
          <div className="flex items-center justify-center py-4">
            <div className="w-5 h-5 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
            <span className="text-steel font-body text-sm">Loading sessions...</span>
          </div>
        ) : (
          <div className="flex items-end gap-4">
            <SessionSelector
              label="Session A"
              sessions={sessions}
              selectedId={sessionAId}
              onChange={setSessionAId}
              accentColor={COLOR_A}
            />

            <button
              type="button"
              onClick={swapSessions}
              className="shrink-0 mb-0.5 p-2 rounded-lg border border-steel/20 text-steel hover:text-chalk hover:border-steel/40 transition-colors"
              title="Swap sessions"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                <path
                  fillRule="evenodd"
                  d="M13.2 2.24a.75.75 0 00.04 1.06l2.1 1.95H6.75a.75.75 0 000 1.5h8.59l-2.1 1.95a.75.75 0 101.02 1.1l3.5-3.25a.75.75 0 000-1.1l-3.5-3.25a.75.75 0 00-1.06.04zm-6.4 8a.75.75 0 00-1.06-.04l-3.5 3.25a.75.75 0 000 1.1l3.5 3.25a.75.75 0 101.02-1.1l-2.1-1.95h8.59a.75.75 0 000-1.5H4.66l2.1-1.95a.75.75 0 00.04-1.06z"
                  clipRule="evenodd"
                />
              </svg>
            </button>

            <SessionSelector
              label="Session B"
              sessions={sessions}
              selectedId={sessionBId}
              onChange={setSessionBId}
              accentColor={COLOR_B}
            />
          </div>
        )}
      </div>

      {/* Loading comparison */}
      {loadingComparison && (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
          <span className="text-steel font-body text-sm">Comparing sessions...</span>
        </div>
      )}

      {/* Comparison error */}
      {compError && (
        <div className="bg-concrete rounded-xl border border-safety-red/30 p-6 text-center">
          <p className="text-safety-red font-body text-sm">{compError}</p>
        </div>
      )}

      {/* Empty state */}
      {!sessionAId && !sessionBId && !loadingComparison && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-12 text-center">
          <p className="font-telemetry text-4xl text-steel/30 mb-4">vs</p>
          <h2 className="font-monument text-lg text-chalk mb-2">Pick Two Sessions</h2>
          <p className="text-steel font-body text-sm max-w-md mx-auto">
            Use the dropdowns above to select two sessions. The comparison will load automatically.
          </p>
        </div>
      )}

      {/* Comparison results */}
      {comparison && !loadingComparison && (
        <div className="space-y-6">
          {/* ── Side-by-side Metadata ─────────────────────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <MetadataCard
              session={comparison.session_a.session}
              label="Session A"
              accentColor={COLOR_A}
            />
            <MetadataCard
              session={comparison.session_b.session}
              label="Session B"
              accentColor={COLOR_B}
            />
          </div>

          {/* ── Total Score Comparison ────────────────────────── */}
          <div className="bg-concrete rounded-xl border border-steel/10 p-6">
            <h2 className="text-lg font-monument text-chalk mb-4">Total Score</h2>
            <div className="flex items-center justify-center gap-8">
              {/* Session A score */}
              <div className="text-center">
                <span className="text-xs font-monument uppercase tracking-wider" style={{ color: COLOR_A }}>
                  Session A
                </span>
                <div className="text-4xl font-monument text-chalk mt-1">
                  {comparison.session_a.session.total_score?.toFixed(1) ?? '--'}
                </div>
                <div className={`text-lg font-monument mt-1 ${gradeColor(comparison.session_a.session.grade)}`}>
                  {comparison.session_a.session.grade ?? '--'}
                </div>
              </div>

              {/* Delta */}
              <div className="text-center px-6 py-3 rounded-lg bg-asphalt border border-steel/10">
                <span className="text-xs font-body text-steel block mb-1">Delta</span>
                <span className={`text-2xl font-monument ${compStats?.totalDelta != null ? deltaColor(compStats.totalDelta) : 'text-steel'}`}>
                  {compStats?.totalDelta != null ? formatDelta(compStats.totalDelta) : '--'}
                </span>
              </div>

              {/* Session B score */}
              <div className="text-center">
                <span className="text-xs font-monument uppercase tracking-wider" style={{ color: COLOR_B }}>
                  Session B
                </span>
                <div className="text-4xl font-monument text-chalk mt-1">
                  {comparison.session_b.session.total_score?.toFixed(1) ?? '--'}
                </div>
                <div className={`text-lg font-monument mt-1 ${gradeColor(comparison.session_b.session.grade)}`}>
                  {comparison.session_b.session.grade ?? '--'}
                </div>
              </div>
            </div>
          </div>

          {/* ── Score Category Comparison ─────────────────────── */}
          <div>
            <h2 className="text-lg font-monument text-chalk mb-4">Score Breakdown</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <ScoreCompareCard
                label="Pace"
                scoreA={comparison.session_a.scores?.pace_score ?? null}
                scoreB={comparison.session_b.scores?.pace_score ?? null}
                max={comparison.session_a.scores?.pace_max ?? 25}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
              <ScoreCompareCard
                label="Consistency"
                scoreA={comparison.session_a.scores?.consistency_score ?? null}
                scoreB={comparison.session_b.scores?.consistency_score ?? null}
                max={comparison.session_a.scores?.consistency_max ?? 25}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
              <ScoreCompareCard
                label="Execution"
                scoreA={comparison.session_a.scores?.execution_score ?? null}
                scoreB={comparison.session_b.scores?.execution_score ?? null}
                max={comparison.session_a.scores?.execution_max ?? 20}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
              <ScoreCompareCard
                label="Robustness"
                scoreA={comparison.session_a.scores?.robustness_score ?? null}
                scoreB={comparison.session_b.scores?.robustness_score ?? null}
                max={comparison.session_a.scores?.robustness_max ?? 15}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
            </div>
          </div>

          {/* ── Chart Panel (Speed / GPS / Sectors / Corners) ── */}
          <CompareChartPanel sessionAId={sessionAId} sessionBId={sessionBId} />

          {/* ── Lap-by-Lap Comparison ────────────────────────── */}
          <div>
            <h2 className="text-lg font-monument text-chalk mb-4">Lap Comparison</h2>
            <div className="bg-concrete rounded-xl border border-steel/10 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-steel/10">
                      <th className="text-left px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                        Metric
                      </th>
                      <th className="text-right px-4 py-3 font-body font-normal text-xs uppercase tracking-wider" style={{ color: COLOR_A }}>
                        Session A
                      </th>
                      <th className="text-right px-4 py-3 font-body font-normal text-xs uppercase tracking-wider" style={{ color: COLOR_B }}>
                        Session B
                      </th>
                      <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                        Delta
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* Lap count */}
                    <CompareRow
                      label="Lap Count"
                      valueA={comparison.session_a.session.n_laps != null ? String(comparison.session_a.session.n_laps) : '--'}
                      valueB={comparison.session_b.session.n_laps != null ? String(comparison.session_b.session.n_laps) : '--'}
                      delta={null}
                      deltaColorClass="text-steel"
                    />

                    {/* Best lap time */}
                    <CompareRow
                      label="Best Lap Time"
                      valueA={formatLapTime(comparison.session_a.session.best_lap_time_s)}
                      valueB={formatLapTime(comparison.session_b.session.best_lap_time_s)}
                      delta={
                        compStats?.bestLapDelta != null
                          ? `${formatDelta(compStats.bestLapDelta, 3)}s`
                          : null
                      }
                      deltaColorClass={
                        compStats?.bestLapDelta != null
                          ? deltaColor(compStats.bestLapDelta, true)
                          : 'text-steel'
                      }
                    />

                    {/* Average lap time */}
                    <CompareRow
                      label="Avg Lap Time"
                      valueA={formatLapTime(comparison.session_a.session.mean_lap_time_s)}
                      valueB={formatLapTime(comparison.session_b.session.mean_lap_time_s)}
                      delta={
                        compStats?.avgLapDelta != null
                          ? `${formatDelta(compStats.avgLapDelta, 3)}s`
                          : null
                      }
                      deltaColorClass={
                        compStats?.avgLapDelta != null
                          ? deltaColor(compStats.avgLapDelta, true)
                          : 'text-steel'
                      }
                    />

                    {/* Valid laps */}
                    <CompareRow
                      label="Valid Laps"
                      valueA={String(comparison.session_a.laps.filter((l) => l.is_valid === 1).length)}
                      valueB={String(comparison.session_b.laps.filter((l) => l.is_valid === 1).length)}
                      delta={null}
                      deltaColorClass="text-steel"
                    />

                    {/* Best lap avg speed */}
                    {(() => {
                      const bestA = comparison.session_a.laps.find((l) => l.is_best === 1);
                      const bestB = comparison.session_b.laps.find((l) => l.is_best === 1);
                      const speedDelta =
                        bestA?.speed_mean_mps != null && bestB?.speed_mean_mps != null
                          ? (bestA.speed_mean_mps - bestB.speed_mean_mps) * 3.6
                          : null;
                      return (
                        <CompareRow
                          label="Best Lap Avg Speed"
                          valueA={bestA ? `${mpsToKmh(bestA.speed_mean_mps)} km/h` : '--'}
                          valueB={bestB ? `${mpsToKmh(bestB.speed_mean_mps)} km/h` : '--'}
                          delta={speedDelta != null ? `${formatDelta(speedDelta)} km/h` : null}
                          deltaColorClass={speedDelta != null ? deltaColor(speedDelta) : 'text-steel'}
                        />
                      );
                    })()}

                    {/* Best lap max speed */}
                    {(() => {
                      const bestA = comparison.session_a.laps.find((l) => l.is_best === 1);
                      const bestB = comparison.session_b.laps.find((l) => l.is_best === 1);
                      const speedDelta =
                        bestA?.speed_max_mps != null && bestB?.speed_max_mps != null
                          ? (bestA.speed_max_mps - bestB.speed_max_mps) * 3.6
                          : null;
                      return (
                        <CompareRow
                          label="Best Lap Max Speed"
                          valueA={bestA ? `${mpsToKmh(bestA.speed_max_mps)} km/h` : '--'}
                          valueB={bestB ? `${mpsToKmh(bestB.speed_max_mps)} km/h` : '--'}
                          delta={speedDelta != null ? `${formatDelta(speedDelta)} km/h` : null}
                          deltaColorClass={speedDelta != null ? deltaColor(speedDelta) : 'text-steel'}
                        />
                      );
                    })()}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* ── Individual Lap Times ─────────────────────────── */}
          {(comparison.session_a.laps.length > 0 || comparison.session_b.laps.length > 0) && (
            <div>
              <h2 className="text-lg font-monument text-chalk mb-4">Individual Lap Times</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <LapTimesTable
                  laps={comparison.session_a.laps}
                  label="Session A"
                  accentColor={COLOR_A}
                />
                <LapTimesTable
                  laps={comparison.session_b.laps}
                  label="Session B"
                  accentColor={COLOR_B}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────

function MetadataCard({
  session,
  label,
  accentColor,
}: {
  session: SessionDetail;
  label: string;
  accentColor: string;
}) {
  return (
    <div
      className="bg-concrete rounded-xl border p-5"
      style={{ borderColor: accentColor + '30' }}
    >
      <h3 className="text-xs font-monument uppercase tracking-wider mb-3" style={{ color: accentColor }}>
        {label}
      </h3>
      <dl className="space-y-2">
        <MetaRow label="File" value={session.csv_filename} />
        <MetaRow label="Driver" value={session.driver_name} />
        <MetaRow label="Track" value={session.track_name || 'Unknown'} />
        <MetaRow label="Type" value={session.session_type || '--'} />
        <MetaRow label="Conditions" value={session.track_state || '--'} />
        <MetaRow label="Date" value={session.session_date} />
      </dl>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-steel text-xs font-body">{label}</dt>
      <dd className="text-xs font-telemetry text-chalk truncate ml-4 max-w-[200px]">{value}</dd>
    </div>
  );
}

function CompareRow({
  label,
  valueA,
  valueB,
  delta,
  deltaColorClass,
}: {
  label: string;
  valueA: string;
  valueB: string;
  delta: string | null;
  deltaColorClass: string;
}) {
  return (
    <tr className="border-b border-steel/5 hover:bg-asphalt/50 transition-colors">
      <td className="px-4 py-3 text-steel font-body text-sm">{label}</td>
      <td className="px-4 py-3 text-right font-telemetry text-chalk text-sm">{valueA}</td>
      <td className="px-4 py-3 text-right font-telemetry text-chalk text-sm">{valueB}</td>
      <td className={`px-4 py-3 text-right font-telemetry text-sm ${deltaColorClass}`}>
        {delta ?? '--'}
      </td>
    </tr>
  );
}

function LapTimesTable({
  laps,
  label,
  accentColor,
}: {
  laps: LapData[];
  label: string;
  accentColor: string;
}) {
  if (laps.length === 0) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-6 text-center">
        <p className="text-steel font-body text-sm">No lap data for {label}</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 overflow-hidden">
      <div className="px-4 py-2 border-b border-steel/10">
        <h4 className="text-xs font-monument uppercase tracking-wider" style={{ color: accentColor }}>
          {label}
        </h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-steel/10">
              <th className="text-left px-3 py-2 text-steel font-body font-normal text-xs">Lap</th>
              <th className="text-right px-3 py-2 text-steel font-body font-normal text-xs">Time</th>
              <th className="text-right px-3 py-2 text-steel font-body font-normal text-xs">Avg km/h</th>
              <th className="text-center px-3 py-2 text-steel font-body font-normal text-xs">Status</th>
            </tr>
          </thead>
          <tbody>
            {laps.map((lap) => {
              const isBest = lap.is_best === 1;
              const isInvalid = lap.is_valid === 0;
              return (
                <tr
                  key={lap.lap_number}
                  className={`border-b border-steel/5 ${isBest ? 'bg-acid-green/5' : ''} ${isInvalid ? 'opacity-50' : ''}`}
                >
                  <td className="px-3 py-2 font-telemetry text-chalk">
                    <span className="flex items-center gap-1">
                      {lap.lap_number}
                      {isBest && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-acid-green/20 text-acid-green font-body uppercase">
                          best
                        </span>
                      )}
                    </span>
                  </td>
                  <td className={`px-3 py-2 text-right font-telemetry ${isBest ? 'text-acid-green' : 'text-chalk'}`}>
                    {formatLapTime(lap.lap_time_s)}
                  </td>
                  <td className="px-3 py-2 text-right font-telemetry text-chalk">
                    {mpsToKmh(lap.speed_mean_mps)}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {isInvalid ? (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-safety-red/20 text-safety-red font-body">
                        Invalid
                      </span>
                    ) : (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-green-500/10 text-green-400 font-body">
                        Valid
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
