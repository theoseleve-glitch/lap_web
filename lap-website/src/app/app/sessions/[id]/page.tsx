'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api, BACKEND_URL } from '@/lib/api-client';
import { SpeedTraceZoom, GpsTrace, GGExplorer } from '@/components/app/charts';
import { SectorPanel, CornerReplay } from '@/components/shared/charts';

// ── Types ────────────────────────────────────────────────────────

interface SessionData {
  session_id: string;
  csv_filename: string;
  driver_name: string;
  track_name: string | null;
  session_type: string;
  track_state: string;
  session_date: string;
  n_laps: number | null;
  best_lap_time_s: number | null;
  mean_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
  notes: string | null;
}

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  speed_mean_mps: number | null;
  speed_max_mps: number | null;
  is_valid: number;
  is_best: number;
  invalid_reason: string | null;
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
  strengths: string[];
  weaknesses: string[];
}

interface CornerData {
  corner_number?: number;
  name?: string;
  coaching?: string;
  entry_speed_mps?: number | null;
  apex_speed_mps?: number | null;
  exit_speed_mps?: number | null;
  time_loss_s?: number | null;
  severity?: string;
}

// ── Helpers ──────────────────────────────────────────────────────

type Tab = 'overview' | 'visualize' | 'corners' | 'performance' | 'laps';

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'visualize', label: 'Visualize' },
  { key: 'corners', label: 'Corners' },
  { key: 'performance', label: 'Performance' },
  { key: 'laps', label: 'Lap Data' },
];

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
  S: 'text-yellow-400 border-yellow-400',
  A: 'text-green-400 border-green-400',
  B: 'text-cyan-400 border-cyan-400',
  C: 'text-yellow-500 border-yellow-500',
  D: 'text-orange-400 border-orange-400',
  F: 'text-red-500 border-red-500',
};

function gradeColorClass(grade: string | null): string {
  if (!grade) return 'text-steel border-steel';
  return GRADE_COLORS[grade.charAt(0).toUpperCase()] || 'text-steel border-steel';
}

// ── Score bar for Overview tab ───────────────────────────────────

function ScoreBar({
  label,
  score,
  max,
  accentColor,
}: {
  label: string;
  score: number | null;
  max: number;
  accentColor: string;
}) {
  const pct = score != null ? Math.min((score / max) * 100, 100) : 0;
  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm mb-1">
        <span className="text-chalk font-body">{label}</span>
        <span className="text-steel font-telemetry">
          {score != null ? score.toFixed(1) : '--'} / {max}
        </span>
      </div>
      <div className="w-full h-2.5 bg-asphalt rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: accentColor }}
        />
      </div>
    </div>
  );
}

// ── Main page component ──────────────────────────────────────────

export default function SessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;

  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [session, setSession] = useState<SessionData | null>(null);
  const [laps, setLaps] = useState<LapData[]>([]);
  const [scores, setScores] = useState<ScoreData | null>(null);
  const [corners, setCorners] = useState<CornerData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch all data on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      setLoading(true);
      setError(null);

      try {
        // Fetch session detail first (required)
        const sessionData = await api.get<SessionData>(`/sessions/${sessionId}`);
        if (cancelled) return;
        setSession(sessionData);

        // Fetch supplementary data in parallel (non-critical)
        const [lapsRes, scoresRes, cornersRes] = await Promise.allSettled([
          api.get<{ laps: LapData[] }>(`/sessions/${sessionId}/laps`),
          api.get<ScoreData>(`/sessions/${sessionId}/scores`),
          api.get<{ corners: CornerData[] }>(`/sessions/${sessionId}/corners`),
        ]);

        if (cancelled) return;

        if (lapsRes.status === 'fulfilled') {
          setLaps(lapsRes.value.laps || []);
        }
        if (scoresRes.status === 'fulfilled') {
          setScores(scoresRes.value);
        }
        if (cornersRes.status === 'fulfilled') {
          setCorners(cornersRes.value.corners || []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load session');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Derived values
  const bestLap = useMemo(() => {
    const best = laps.find((l) => l.is_best === 1);
    return best?.lap_number ?? (laps.length > 0 ? laps[0].lap_number : null);
  }, [laps]);

  const gpsLaps = useMemo(() => laps.map((l) => l.lap_number), [laps]);

  const handleTabChange = useCallback((tab: Tab) => {
    setActiveTab(tab);
  }, []);

  // ── Loading / error states ─────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-acid-green border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-steel font-body">Loading session...</p>
        </div>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <h1 className="text-2xl font-monument text-chalk mb-2">Session Not Found</h1>
          <p className="text-steel font-body mb-4">{error || 'The session could not be loaded.'}</p>
          <Link
            href="/app/sessions"
            className="text-acid-green hover:underline font-body text-sm"
          >
            Back to Sessions
          </Link>
        </div>
      </div>
    );
  }

  // ── Page render ────────────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/app/sessions"
              className="text-steel hover:text-chalk text-sm font-body transition-colors"
            >
              Sessions
            </Link>
            <span className="text-steel/40">/</span>
          </div>
          <h1 className="text-2xl font-monument text-chalk tracking-tight">
            {session.csv_filename}
          </h1>
          <p className="text-steel text-sm font-body mt-1">
            {session.driver_name}
            {session.track_name ? ` \u2022 ${session.track_name}` : ''}
            {` \u2022 ${session.session_date}`}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Grade badge */}
          {session.grade && (
            <div
              className={`w-14 h-14 flex items-center justify-center rounded-lg border-2 font-monument text-2xl ${gradeColorClass(session.grade)}`}
            >
              {session.grade}
            </div>
          )}

          {/* Report download */}
          <a
            href={`${BACKEND_URL}/api/v1/sessions/${sessionId}/report?format=html`}
            className="px-4 py-2 bg-concrete border border-steel/20 rounded-lg text-sm text-chalk font-body hover:bg-steel/10 transition-colors"
            target="_blank"
            rel="noopener noreferrer"
          >
            Download Report
          </a>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-6 border-b border-steel/10">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => handleTabChange(tab.key)}
            className={`px-4 py-2.5 text-sm font-body transition-colors relative ${
              activeTab === tab.key
                ? 'text-acid-green'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {tab.label}
            {activeTab === tab.key && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-acid-green" />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && (
        <OverviewTab session={session} scores={scores} laps={laps} bestLap={bestLap} />
      )}
      {activeTab === 'visualize' && (
        <VisualizeTab sessionId={sessionId} gpsLaps={gpsLaps} bestLap={bestLap} />
      )}
      {activeTab === 'corners' && <CornersTab corners={corners} sessionId={sessionId} />}
      {activeTab === 'performance' && (
        <PerformanceTab session={session} scores={scores} sessionId={sessionId} />
      )}
      {activeTab === 'laps' && <LapDataTab laps={laps} />}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// 1. Overview Tab
// ══════════════════════════════════════════════════════════════════

function OverviewTab({
  session,
  scores,
  laps,
  bestLap,
}: {
  session: SessionData;
  scores: ScoreData | null;
  laps: LapData[];
  bestLap: number | null;
}) {
  const bestLapData = laps.find((l) => l.is_best === 1);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left column: Score breakdown */}
      <div className="lg:col-span-2">
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h2 className="text-lg font-monument text-chalk mb-4">Score Breakdown</h2>
          {scores ? (
            <div>
              {/* Total score */}
              <div className="flex items-center gap-4 mb-6 pb-4 border-b border-steel/10">
                <div className="text-4xl font-monument text-chalk">
                  {session.total_score != null
                    ? session.total_score.toFixed(1)
                    : '--'}
                </div>
                <div className="text-steel font-body text-sm">/ 100</div>
                {session.grade && (
                  <div
                    className={`ml-auto w-12 h-12 flex items-center justify-center rounded-lg border-2 font-monument text-xl ${gradeColorClass(session.grade)}`}
                  >
                    {session.grade}
                  </div>
                )}
              </div>

              {/* Category bars */}
              <ScoreBar
                label="Pace"
                score={scores.pace_score}
                max={scores.pace_max ?? 25}
                accentColor="#B6FF2E"
              />
              <ScoreBar
                label="Consistency"
                score={scores.consistency_score}
                max={scores.consistency_max ?? 25}
                accentColor="#00d4ff"
              />
              <ScoreBar
                label="Execution"
                score={scores.execution_score}
                max={scores.execution_max ?? 20}
                accentColor="#D946EF"
              />
              <ScoreBar
                label="Robustness"
                score={scores.robustness_score}
                max={scores.robustness_max ?? 15}
                accentColor="#FF6A00"
              />
              <ScoreBar
                label="Adaptation"
                score={scores.adaptation_score}
                max={15}
                accentColor="#FFD400"
              />

              {/* Strengths / Weaknesses */}
              {(scores.strengths?.length > 0 || scores.weaknesses?.length > 0) && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6 pt-4 border-t border-steel/10">
                  {scores.strengths?.length > 0 && (
                    <div>
                      <h3 className="text-sm font-body text-green-400 mb-2">
                        Strengths
                      </h3>
                      <ul className="space-y-1">
                        {scores.strengths.map((s, i) => (
                          <li
                            key={i}
                            className="text-sm text-chalk/80 font-body"
                          >
                            {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {scores.weaknesses?.length > 0 && (
                    <div>
                      <h3 className="text-sm font-body text-red-400 mb-2">
                        Areas to Improve
                      </h3>
                      <ul className="space-y-1">
                        {scores.weaknesses.map((w, i) => (
                          <li
                            key={i}
                            className="text-sm text-chalk/80 font-body"
                          >
                            {w}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-steel font-body text-sm">
              No score data available for this session.
            </p>
          )}
        </div>
      </div>

      {/* Right column: Session metadata + best lap */}
      <div className="space-y-6">
        {/* Metadata card */}
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h2 className="text-lg font-monument text-chalk mb-4">Session Info</h2>
          <dl className="space-y-3">
            <MetaRow label="File" value={session.csv_filename} />
            <MetaRow label="Driver" value={session.driver_name} />
            <MetaRow label="Track" value={session.track_name || 'Unknown'} />
            <MetaRow label="Type" value={session.session_type} />
            <MetaRow label="Conditions" value={session.track_state} />
            <MetaRow label="Date" value={session.session_date} />
            <MetaRow
              label="Laps"
              value={session.n_laps != null ? String(session.n_laps) : '--'}
            />
          </dl>
        </div>

        {/* Best lap card */}
        {bestLapData && (
          <div className="bg-concrete rounded-xl border border-acid-green/20 p-6">
            <h2 className="text-lg font-monument text-acid-green mb-4">
              Best Lap #{bestLap}
            </h2>
            <dl className="space-y-3">
              <MetaRow
                label="Time"
                value={formatLapTime(bestLapData.lap_time_s)}
                highlight
              />
              <MetaRow
                label="Avg Speed"
                value={`${mpsToKmh(bestLapData.speed_mean_mps)} km/h`}
              />
              <MetaRow
                label="Max Speed"
                value={`${mpsToKmh(bestLapData.speed_max_mps)} km/h`}
              />
            </dl>
          </div>
        )}
      </div>
    </div>
  );
}

function MetaRow({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex justify-between">
      <dt className="text-steel text-sm font-body">{label}</dt>
      <dd
        className={`text-sm font-telemetry ${
          highlight ? 'text-acid-green' : 'text-chalk'
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// 2. Visualize Tab
// ══════════════════════════════════════════════════════════════════

function VisualizeTab({
  sessionId,
  gpsLaps,
  bestLap,
}: {
  sessionId: string;
  gpsLaps: number[];
  bestLap: number | null;
}) {
  const apiBase = BACKEND_URL;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left: GPS Map (tall) */}
      <div className="lg:col-span-1 lg:row-span-2">
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">GPS Track Map</h3>
          <GpsTrace
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full"
          />
        </div>
      </div>

      {/* Top-right: Speed Trace */}
      <div className="lg:col-span-2">
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">Speed Trace</h3>
          <SpeedTraceZoom
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full"
          />
        </div>
      </div>

      {/* Bottom-right: GG Diagram */}
      <div className="lg:col-span-2">
        <div className="bg-concrete rounded-xl border border-steel/10 p-4">
          <h3 className="text-sm font-monument text-chalk mb-3">G-G Diagram</h3>
          <GGExplorer
            sessionId={sessionId}
            apiBase={apiBase}
            gpsLaps={gpsLaps}
            bestLap={bestLap}
            className="w-full"
          />
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// 3. Corners Tab
// ══════════════════════════════════════════════════════════════════

function CornersTab({ corners, sessionId }: { corners: CornerData[]; sessionId: string }) {
  if (corners.length === 0) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center">
        <p className="text-steel font-body">
          No corner coaching data available for this session.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-monument text-chalk">Corner Coaching</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {corners.map((corner, idx) => {
          const cornerNum = corner.corner_number ?? idx + 1;
          const severityColor =
            corner.severity === 'high'
              ? 'border-safety-red/40'
              : corner.severity === 'medium'
                ? 'border-marshal-yellow/40'
                : 'border-steel/10';

          return (
            <div
              key={cornerNum}
              className={`bg-concrete rounded-xl border p-5 ${severityColor}`}
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="w-8 h-8 flex items-center justify-center rounded-full bg-asphalt text-acid-green font-monument text-sm">
                  {cornerNum}
                </div>
                <h3 className="text-chalk font-body text-sm font-medium">
                  {corner.name || `Corner ${cornerNum}`}
                </h3>
                {corner.time_loss_s != null && (
                  <span className="ml-auto text-xs font-telemetry text-safety-red">
                    +{corner.time_loss_s.toFixed(3)}s
                  </span>
                )}
              </div>

              {corner.coaching && (
                <p className="text-chalk/80 text-sm font-body mb-3">
                  {corner.coaching}
                </p>
              )}

              {/* Speed metrics */}
              {(corner.entry_speed_mps != null ||
                corner.apex_speed_mps != null ||
                corner.exit_speed_mps != null) && (
                <div className="flex gap-4 text-xs font-telemetry">
                  {corner.entry_speed_mps != null && (
                    <div>
                      <span className="text-steel">Entry </span>
                      <span className="text-chalk">
                        {mpsToKmh(corner.entry_speed_mps)} km/h
                      </span>
                    </div>
                  )}
                  {corner.apex_speed_mps != null && (
                    <div>
                      <span className="text-steel">Apex </span>
                      <span className="text-chalk">
                        {mpsToKmh(corner.apex_speed_mps)} km/h
                      </span>
                    </div>
                  )}
                  {corner.exit_speed_mps != null && (
                    <div>
                      <span className="text-steel">Exit </span>
                      <span className="text-chalk">
                        {mpsToKmh(corner.exit_speed_mps)} km/h
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Corner Replay — speed profile comparison with playback */}
      <div className="mt-6">
        <h2 className="text-lg font-monument text-chalk mb-4">Corner Replay</h2>
        <CornerReplay
          sessionId={sessionId}
          className="bg-concrete rounded-xl border border-steel/10"
        />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// 4. Performance Tab
// ══════════════════════════════════════════════════════════════════

function PerformanceTab({
  session,
  scores,
  sessionId,
}: {
  session: SessionData;
  scores: ScoreData | null;
  sessionId: string;
}) {
  if (!scores) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center">
        <p className="text-steel font-body">
          No performance data available for this session.
        </p>
      </div>
    );
  }

  const metrics: {
    label: string;
    value: string;
    sub: string;
    color: string;
  }[] = [
    {
      label: 'Total Score',
      value:
        session.total_score != null
          ? session.total_score.toFixed(1)
          : '--',
      sub: '/ 100',
      color: 'text-chalk',
    },
    {
      label: 'Grade',
      value: session.grade || '--',
      sub: '',
      color: gradeColorClass(session.grade).split(' ')[0],
    },
    {
      label: 'Pace',
      value:
        scores.pace_score != null ? scores.pace_score.toFixed(1) : '--',
      sub: `/ ${scores.pace_max ?? 25}`,
      color: 'text-acid-green',
    },
    {
      label: 'Consistency',
      value:
        scores.consistency_score != null
          ? scores.consistency_score.toFixed(1)
          : '--',
      sub: `/ ${scores.consistency_max ?? 25}`,
      color: 'text-cyan-400',
    },
    {
      label: 'Execution',
      value:
        scores.execution_score != null
          ? scores.execution_score.toFixed(1)
          : '--',
      sub: `/ ${scores.execution_max ?? 20}`,
      color: 'text-racing-purple',
    },
    {
      label: 'Robustness',
      value:
        scores.robustness_score != null
          ? scores.robustness_score.toFixed(1)
          : '--',
      sub: `/ ${scores.robustness_max ?? 15}`,
      color: 'text-pit-orange',
    },
    {
      label: 'Adaptation',
      value:
        scores.adaptation_score != null
          ? scores.adaptation_score.toFixed(1)
          : '--',
      sub: '/ 15',
      color: 'text-marshal-yellow',
    },
  ];

  return (
    <div>
      <h2 className="text-lg font-monument text-chalk mb-4">Performance Metrics</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {metrics.map((m) => (
          <div
            key={m.label}
            className="bg-concrete rounded-xl border border-steel/10 p-5"
          >
            <p className="text-steel text-xs font-body uppercase tracking-wider mb-2">
              {m.label}
            </p>
            <div className="flex items-baseline gap-1.5">
              <span className={`text-3xl font-monument ${m.color}`}>
                {m.value}
              </span>
              {m.sub && (
                <span className="text-steel text-sm font-body">{m.sub}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Strengths and weaknesses */}
      {(scores.strengths?.length > 0 || scores.weaknesses?.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
          {scores.strengths?.length > 0 && (
            <div className="bg-concrete rounded-xl border border-green-500/20 p-6">
              <h3 className="text-sm font-monument text-green-400 mb-3">
                Strengths
              </h3>
              <ul className="space-y-2">
                {scores.strengths.map((s, i) => (
                  <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
                    <span className="text-green-400 shrink-0">+</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {scores.weaknesses?.length > 0 && (
            <div className="bg-concrete rounded-xl border border-red-500/20 p-6">
              <h3 className="text-sm font-monument text-red-400 mb-3">
                Areas to Improve
              </h3>
              <ul className="space-y-2">
                {scores.weaknesses.map((w, i) => (
                  <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
                    <span className="text-red-400 shrink-0">-</span>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Sector Analysis */}
      <div className="mt-6">
        <SectorPanel sessionId={sessionId} className="bg-concrete rounded-xl border border-steel/10" />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// 5. Lap Data Tab
// ══════════════════════════════════════════════════════════════════

function LapDataTab({ laps }: { laps: LapData[] }) {
  if (laps.length === 0) {
    return (
      <div className="bg-concrete rounded-xl border border-steel/10 p-8 text-center">
        <p className="text-steel font-body">No lap data available for this session.</p>
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-lg font-monument text-chalk mb-4">Lap Data</h2>
      <div className="bg-concrete rounded-xl border border-steel/10 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-steel/10">
                <th className="text-left px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                  Lap
                </th>
                <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                  Time
                </th>
                <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                  Avg Speed
                </th>
                <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                  Max Speed
                </th>
                <th className="text-center px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {laps.map((lap) => {
                const isBest = lap.is_best === 1;
                const isInvalid = lap.is_valid === 0;
                return (
                  <tr
                    key={lap.lap_number}
                    className={`border-b border-steel/5 transition-colors hover:bg-asphalt/50 ${
                      isBest ? 'bg-acid-green/5' : ''
                    } ${isInvalid ? 'opacity-50' : ''}`}
                  >
                    <td className="px-4 py-3 font-telemetry text-chalk">
                      <span className="flex items-center gap-2">
                        {lap.lap_number}
                        {isBest && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-acid-green/20 text-acid-green font-body uppercase tracking-wide">
                            Best
                          </span>
                        )}
                      </span>
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-telemetry ${
                        isBest ? 'text-acid-green' : 'text-chalk'
                      }`}
                    >
                      {formatLapTime(lap.lap_time_s)}
                    </td>
                    <td className="px-4 py-3 text-right font-telemetry text-chalk">
                      {mpsToKmh(lap.speed_mean_mps)} km/h
                    </td>
                    <td className="px-4 py-3 text-right font-telemetry text-chalk">
                      {mpsToKmh(lap.speed_max_mps)} km/h
                    </td>
                    <td className="px-4 py-3 text-center">
                      {isInvalid ? (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded bg-safety-red/20 text-safety-red font-body"
                          title={lap.invalid_reason || 'Invalid lap'}
                        >
                          {lap.invalid_reason || 'Invalid'}
                        </span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-400 font-body">
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
    </div>
  );
}
