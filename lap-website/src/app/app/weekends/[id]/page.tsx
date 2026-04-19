'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { StatCard, QueryError, SkeletonStatCards, SkeletonBox } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { useEntityDelete } from '@/hooks/useEntityDelete';
import { DeleteConfirmPanel } from '@/components/app/DeleteConfirmPanel';

/* ── Types ──────────────────────────────────────────────── */

interface Pillars {
  pace: number | null;
  pace_max: number | null;
  consistency: number | null;
  consistency_max: number | null;
  execution: number | null;
  execution_max: number | null;
  robustness: number | null;
  robustness_max: number | null;
  adaptation: number | null;
}

interface LapTime {
  lap: number;
  time: number;
}

interface SessionEntry {
  id: string;
  order: number;
  date: string;
  type: string;
  driver_name: string;
  track_name: string;
  laps: number;
  best_time: number | null;
  mean_time: number | null;
  score: number | null;
  grade: string | null;
  pillars: Pillars | null;
  lap_times: LapTime[];
}

interface ProgressionPoint {
  order: number;
  session_id: string;
  label: string;
  score: number | null;
  best_time: number | null;
  mean_time: number | null;
  laps: number;
}

interface Summary {
  total_sessions: number;
  total_laps: number;
  best_time: number | null;
  avg_score: number | null;
  best_score: number | null;
  worst_score: number | null;
  score_delta: number | null;
  time_delta: number | null;
  grade_counts: Record<string, number>;
}

interface WeekendReport {
  sessions: SessionEntry[];
  summary: Summary | null;
  progression: ProgressionPoint[];
  pillar_breakdown: Array<Pillars & { session_id: string; order: number; label: string }>;
}

interface WeekendDetail {
  id: number;
  name: string;
  track_name: string;
  track_id: string | null;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  session_count: number;
  sessions: Array<{ session_id: string }>;
}

interface AvailableSession {
  session_id: string;
  csv_filename: string;
  session_date: string;
  driver_name: string;
  total_score: number | null;
  best_lap_time_s: number | null;
  n_laps: number;
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m > 0) return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
  return `${sec.toFixed(3)}s`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-gold';
  if (score >= 40) return 'text-marshal-yellow';
  return 'text-safety-red';
}

function deltaArrow(delta: number | null, inverted = false): string {
  if (delta == null || delta === 0) return '';
  const improved = inverted ? delta < 0 : delta > 0;
  return improved ? ' ↑' : ' ↓';
}

function pillarColor(score: number | null, max: number | null): string {
  if (score == null || max == null || max === 0) return 'bg-steel/30';
  const pct = score / max;
  if (pct >= 0.8) return 'bg-acid-green';
  if (pct >= 0.6) return 'bg-gold';
  if (pct >= 0.4) return 'bg-marshal-yellow';
  return 'bg-safety-red';
}

/* ── Pillar Bar ─────────────────────────────────────────── */

function PillarBar({ label, score, max }: { label: string; score: number | null; max: number | null }) {
  const pct = score != null && max ? Math.min(100, (score / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="font-telemetry text-[10px] text-steel w-24 shrink-0 uppercase">{label}</span>
      <div className="flex-1 h-2 bg-asphalt/60 overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${pillarColor(score, max)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-telemetry text-xs text-chalk w-14 text-right">
        {score != null ? score.toFixed(0) : '—'} / {max ?? '—'}
      </span>
    </div>
  );
}

/* ── Progression Chart (SVG) ────────────────────────────── */

function ProgressionChart({
  points,
  valueKey,
  label,
  color,
  format,
  inverted = false,
}: {
  points: ProgressionPoint[];
  valueKey: 'score' | 'best_time' | 'mean_time';
  label: string;
  color: string;
  format: (v: number) => string;
  inverted?: boolean;
}) {
  const values = points.map((p) => p[valueKey]).filter((v): v is number => v != null);
  if (values.length < 2) return null;

  const W = 400;
  const H = 120;
  const PAD = 30;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const pts = points
    .map((p, i) => {
      const v = p[valueKey];
      if (v == null) return null;
      const x = PAD + (i / (points.length - 1)) * (W - PAD * 2);
      let y: number;
      if (inverted) {
        y = PAD + ((v - min) / range) * (H - PAD * 2);
      } else {
        y = H - PAD - ((v - min) / range) * (H - PAD * 2);
      }
      return { x, y, v, label: p.label };
    })
    .filter(Boolean) as Array<{ x: number; y: number; v: number; label: string }>;

  const linePath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');

  return (
    <div>
      <h4 className="font-telemetry text-[10px] uppercase tracking-wider text-steel mb-2">{label}</h4>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="xMidYMid meet">
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const y = PAD + f * (H - PAD * 2);
          return <line key={f} x1={PAD} x2={W - PAD} y1={y} y2={y} stroke="var(--steel)" strokeOpacity="0.1" />;
        })}
        {/* Line */}
        <path d={linePath} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        {/* Points */}
        {pts.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r="4" fill={color} />
            <text x={p.x} y={p.y - 8} textAnchor="middle" fill="var(--chalk)" fontSize="8" fontFamily="var(--font-telemetry)">
              {format(p.v)}
            </text>
            <text x={p.x} y={H - 4} textAnchor="middle" fill="var(--steel)" fontSize="7" fontFamily="var(--font-telemetry)">
              S{i + 1}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

/* ── Add Sessions Modal ─────────────────────────────────── */

function AddSessionPanel({
  weekendId,
  existingIds,
  onClose,
}: {
  weekendId: number;
  existingIds: Set<string>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');

  const { data: sessionsData } = useQuery({
    queryKey: ['all-sessions-for-weekend'],
    queryFn: () => api.get<{ sessions: AvailableSession[] }>('/sessions'),
  });

  const available = useMemo(() => {
    const all = sessionsData?.sessions ?? [];
    let filtered = all.filter((s) => !existingIds.has(s.session_id));
    if (search) {
      const q = search.toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.csv_filename?.toLowerCase().includes(q) ||
          s.driver_name?.toLowerCase().includes(q) ||
          s.session_date?.includes(q),
      );
    }
    return filtered.slice(0, 20);
  }, [sessionsData, existingIds, search]);

  const addMutation = useMutation({
    mutationFn: (sessionId: string) =>
      api.post(`/weekends/${weekendId}/sessions`, { session_id: sessionId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['weekend', String(weekendId)] });
      queryClient.invalidateQueries({ queryKey: ['weekend-report', String(weekendId)] });
    },
  });

  return (
    <div className="bg-concrete border border-steel/20 p-4 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-monument text-sm text-chalk">Add Sessions</h3>
        <button type="button" onClick={onClose} className="text-steel hover:text-chalk text-sm">Close</button>
      </div>
      <input
        type="text"
        placeholder="Search sessions..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full bg-asphalt border border-steel/30 px-3 py-2 text-chalk font-body text-sm mb-3
          placeholder:text-steel/50 focus:outline-none focus:border-gold"
      />
      {available.length === 0 ? (
        <p className="text-steel text-sm">No sessions available to add.</p>
      ) : (
        <div className="space-y-1 max-h-60 overflow-y-auto">
          {available.map((s) => (
            <div key={s.session_id} className="flex items-center justify-between py-1.5 px-2 hover:bg-asphalt/40">
              <div className="min-w-0">
                <span className="text-chalk font-body text-sm block truncate">{s.csv_filename}</span>
                <span className="text-steel font-telemetry text-[10px]">
                  {s.driver_name} · {s.session_date} · {s.n_laps} laps
                  {s.best_lap_time_s != null && ` · ${fmtTime(s.best_lap_time_s)}`}
                </span>
              </div>
              <button
                type="button"
                onClick={() => addMutation.mutate(s.session_id)}
                disabled={addMutation.isPending}
                className="shrink-0 px-3 py-1 bg-gold text-white font-telemetry text-[10px] hover:bg-gold/80 disabled:opacity-50"
              >
                Add
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function WeekendDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const id = params.id as string;
  const [showAddSessions, setShowAddSessions] = useState(false);
  const [activeSession, setActiveSession] = useState<string | null>(null);

  const del = useEntityDelete({
    entity: 'weekend',
    id: id,
    endpoint: `/weekends/${id}`,
    invalidate: [['weekends']],
    redirectTo: '/app/weekends',
  });

  const { data: weekend, isLoading: weekendLoading, error: weekendError, refetch } = useQuery({
    queryKey: ['weekend', id],
    queryFn: () => api.get<WeekendDetail>(`/weekends/${id}`),
  });

  const { data: report, isLoading: reportLoading } = useQuery({
    queryKey: ['weekend-report', id],
    queryFn: () => api.get<WeekendReport>(`/weekends/${id}/report`),
    enabled: !!weekend,
  });

  const removeMutation = useMutation({
    mutationFn: (sessionId: string) => api.delete(`/weekends/${id}/sessions/${sessionId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['weekend', id] });
      queryClient.invalidateQueries({ queryKey: ['weekend-report', id] });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (sessionIds: string[]) =>
      api.post(`/weekends/${id}/reorder`, { session_ids: sessionIds }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['weekend-report', id] });
    },
  });

  const moveSession = (index: number, direction: 'up' | 'down') => {
    const ids = sessions.map((s) => s.id);
    const target = direction === 'up' ? index - 1 : index + 1;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    reorderMutation.mutate(ids);
  };

  const sessions = report?.sessions ?? [];
  const summary = report?.summary;
  const progression = report?.progression ?? [];
  const pillarBreakdown = report?.pillar_breakdown ?? [];

  const existingIds = useMemo(
    () => new Set(sessions.map((s) => s.id)),
    [sessions],
  );

  const selectedSession = activeSession ? sessions.find((s) => s.id === activeSession) : null;

  if (weekendLoading) {
    return (
      <div>
        <SkeletonBox className="h-6 w-40 mb-2" />
        <SkeletonStatCards count={4} />
      </div>
    );
  }

  if (weekendError) {
    return <QueryError message="Couldn't load weekend." onRetry={() => refetch()} />;
  }

  if (!weekend) {
    return (
      <div className="bg-concrete border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Weekend not found</h2>
        <Link href="/app/weekends" className="text-gold font-telemetry text-xs hover:underline">
          Back to weekends
        </Link>
      </div>
    );
  }

  return (
    <div>
      <PageIntro
        title={weekend.name}
        subtitle={`${weekend.track_name ?? 'No track'} · ${weekend.start_date}${weekend.end_date && weekend.end_date !== weekend.start_date ? ` – ${weekend.end_date}` : ''}`}
        actions={
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowAddSessions(!showAddSessions)}
              className="px-4 py-2 bg-gold text-white font-telemetry text-sm hover:bg-gold/80 transition-colors"
            >
              + Add Sessions
            </button>
            <button
              type="button"
              onClick={del.requestDelete}
              className="px-4 py-2 border border-safety-red/30 text-safety-red font-telemetry text-sm hover:bg-safety-red/10 transition-colors"
            >
              Delete
            </button>
            <Link
              href="/app/weekends"
              className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm hover:text-chalk hover:border-steel/60 transition-colors"
            >
              ← All Weekends
            </Link>
          </div>
        }
      />

      <DeleteConfirmPanel {...del} entityName={weekend.name} entityType="weekend" />

      {showAddSessions && (
        <AddSessionPanel
          weekendId={weekend.id}
          existingIds={existingIds}
          onClose={() => setShowAddSessions(false)}
        />
      )}

      {/* ── Weekend Summary ─────────────────────────────── */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <StatCard label="Sessions" value={summary.total_sessions} />
          <StatCard label="Total Laps" value={summary.total_laps} />
          <StatCard
            label="Best Time"
            value={fmtTime(summary.best_time)}
          />
          <StatCard
            label="Avg Score"
            value={summary.avg_score != null ? `${summary.avg_score}` : '—'}
            trend={
              summary.score_delta == null ? 'neutral' :
              summary.score_delta > 0 ? 'up' : summary.score_delta < 0 ? 'down' : 'neutral'
            }
          />
        </div>
      )}

      {/* ── Score & Time Deltas ──────────────────────────── */}
      {summary && (summary.score_delta != null || summary.time_delta != null) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          {summary.score_delta != null && (
            <div className="bg-concrete border border-steel/20 p-4">
              <span className="font-telemetry text-[10px] uppercase text-steel block mb-1">Score Progression</span>
              <span className={`font-monument text-2xl ${summary.score_delta > 0 ? 'text-acid-green' : summary.score_delta < 0 ? 'text-safety-red' : 'text-chalk'}`}>
                {summary.score_delta > 0 ? '+' : ''}{summary.score_delta}
                <span className="text-sm ml-1">{deltaArrow(summary.score_delta)}</span>
              </span>
              <span className="font-body text-steel text-xs block mt-1">
                First → Last session
              </span>
            </div>
          )}
          {summary.time_delta != null && (
            <div className="bg-concrete border border-steel/20 p-4">
              <span className="font-telemetry text-[10px] uppercase text-steel block mb-1">Lap Time Progression</span>
              <span className={`font-monument text-2xl ${summary.time_delta < 0 ? 'text-acid-green' : summary.time_delta > 0 ? 'text-safety-red' : 'text-chalk'}`}>
                {summary.time_delta > 0 ? '+' : ''}{summary.time_delta.toFixed(3)}s
                <span className="text-sm ml-1">{deltaArrow(summary.time_delta, true)}</span>
              </span>
              <span className="font-body text-steel text-xs block mt-1">
                First → Last session best lap
              </span>
            </div>
          )}
        </div>
      )}

      {weekend.notes && (
        <div className="bg-concrete border border-steel/20 p-4 mb-6">
          <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-2">Notes</h2>
          <p className="text-chalk font-body text-sm">{weekend.notes}</p>
        </div>
      )}

      {/* ── Progression Charts ──────────────────────────── */}
      {progression.length >= 2 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="bg-concrete border border-steel/20 p-4">
            <ProgressionChart
              points={progression}
              valueKey="score"
              label="Score Trend"
              color="var(--acid-green)"
              format={(v) => v.toFixed(0)}
            />
          </div>
          <div className="bg-concrete border border-steel/20 p-4">
            <ProgressionChart
              points={progression}
              valueKey="best_time"
              label="Best Lap Trend"
              color="var(--pit-orange)"
              format={(v) => fmtTime(v)}
              inverted
            />
          </div>
        </div>
      )}

      {/* ── Session Cards ───────────────────────────────── */}
      <h2 className="font-monument text-lg text-chalk mb-3">
        Sessions
        <span className="text-steel font-telemetry text-sm ml-2">{sessions.length}</span>
      </h2>

      {reportLoading ? (
        <SkeletonBox className="h-40 w-full" />
      ) : sessions.length === 0 ? (
        <div className="bg-concrete border border-steel/20 p-8 text-center">
          <p className="text-steel font-body text-sm mb-3">No sessions in this weekend yet.</p>
          <button
            type="button"
            onClick={() => setShowAddSessions(true)}
            className="px-4 py-2 bg-gold text-white font-telemetry text-sm hover:bg-gold/80"
          >
            + Add Sessions
          </button>
        </div>
      ) : (
        <div className="space-y-3 mb-6">
          {sessions.map((s, i) => {
            const isActive = activeSession === s.id;
            const isBestTime = summary?.best_time != null && s.best_time === summary.best_time;
            const isBestScore = summary?.best_score != null && s.score === summary.best_score;

            return (
              <div key={s.id} className={`bg-concrete border p-4 transition-colors ${isActive ? 'border-gold/50' : 'border-steel/20 hover:border-steel/40'}`}>
                {/* Header row */}
                <div className="flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => setActiveSession(isActive ? null : s.id)}
                    className="flex items-center gap-3 min-w-0 text-left flex-1"
                  >
                    <span className="font-monument text-lg text-steel/40 w-8 shrink-0">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <div className="min-w-0">
                      <span className="font-monument text-sm text-chalk block truncate">
                        {s.type?.toUpperCase() ?? 'SESSION'} — {s.driver_name}
                      </span>
                      <span className="font-telemetry text-[10px] text-steel">
                        {s.date} · {s.laps} laps
                      </span>
                    </div>
                  </button>

                  <div className="flex items-center gap-4 shrink-0">
                    {/* Best time */}
                    <div className="text-right">
                      <span className="font-telemetry text-[10px] text-steel block">BEST</span>
                      <span className={`font-telemetry text-sm ${isBestTime ? 'text-acid-green' : 'text-chalk'}`}>
                        {fmtTime(s.best_time)}
                      </span>
                    </div>
                    {/* Score */}
                    <div className="text-right">
                      <span className="font-telemetry text-[10px] text-steel block">SCORE</span>
                      <span className={`font-telemetry text-sm ${isBestScore ? 'text-acid-green' : scoreColor(s.score)}`}>
                        {s.score != null ? s.score.toFixed(1) : '—'}
                        {s.grade && <span className="ml-1 text-xs opacity-70">{s.grade}</span>}
                      </span>
                    </div>
                    {/* Actions */}
                    <div className="flex items-center gap-1">
                      {sessions.length > 1 && (
                        <div className="flex flex-col mr-1">
                          <button
                            type="button"
                            onClick={() => moveSession(i, 'up')}
                            disabled={i === 0 || reorderMutation.isPending}
                            className="px-1 py-0 text-steel/40 hover:text-chalk disabled:opacity-20 font-telemetry text-[10px] leading-none"
                            title="Move up"
                          >
                            ▲
                          </button>
                          <button
                            type="button"
                            onClick={() => moveSession(i, 'down')}
                            disabled={i === sessions.length - 1 || reorderMutation.isPending}
                            className="px-1 py-0 text-steel/40 hover:text-chalk disabled:opacity-20 font-telemetry text-[10px] leading-none"
                            title="Move down"
                          >
                            ▼
                          </button>
                        </div>
                      )}
                      <Link
                        href={`/app/sessions/${s.id}`}
                        className="px-2 py-1 border border-steel/30 text-steel font-telemetry text-[10px] hover:text-chalk hover:border-steel/60"
                      >
                        Open
                      </Link>
                      <button
                        type="button"
                        onClick={() => removeMutation.mutate(s.id)}
                        className="px-2 py-1 text-steel/40 hover:text-safety-red font-telemetry text-[10px]"
                        title="Remove from weekend"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                </div>

                {/* Expanded: pillar breakdown + lap times */}
                {isActive && s.pillars && (
                  <div className="mt-4 pt-3 border-t border-steel/10">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Pillars */}
                      <div className="space-y-2">
                        <h4 className="font-telemetry text-[10px] uppercase text-steel mb-2">Score Breakdown</h4>
                        <PillarBar label="Pace" score={s.pillars.pace} max={s.pillars.pace_max} />
                        <PillarBar label="Consistency" score={s.pillars.consistency} max={s.pillars.consistency_max} />
                        <PillarBar label="Execution" score={s.pillars.execution} max={s.pillars.execution_max} />
                        <PillarBar label="Robustness" score={s.pillars.robustness} max={s.pillars.robustness_max} />
                        {s.pillars.adaptation != null && (
                          <PillarBar label="Adaptation" score={s.pillars.adaptation} max={15} />
                        )}
                      </div>

                      {/* Mini lap times */}
                      {s.lap_times.length > 0 && (
                        <div>
                          <h4 className="font-telemetry text-[10px] uppercase text-steel mb-2">Lap Times</h4>
                          <MiniLapChart lapTimes={s.lap_times} bestTime={s.best_time} />
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Pillar Comparison Across Sessions ────────────── */}
      {pillarBreakdown.length >= 2 && (
        <div className="bg-concrete border border-steel/20 p-4 mb-6">
          <h3 className="font-monument text-sm text-chalk mb-3">Pillar Comparison Across Sessions</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-steel/10">
                  <th className="text-left font-telemetry text-[10px] uppercase text-steel py-2 pr-4">Session</th>
                  <th className="text-right font-telemetry text-[10px] uppercase text-steel py-2 px-2">Pace</th>
                  <th className="text-right font-telemetry text-[10px] uppercase text-steel py-2 px-2">Consistency</th>
                  <th className="text-right font-telemetry text-[10px] uppercase text-steel py-2 px-2">Execution</th>
                  <th className="text-right font-telemetry text-[10px] uppercase text-steel py-2 px-2">Robustness</th>
                  <th className="text-right font-telemetry text-[10px] uppercase text-steel py-2 px-2">Total</th>
                </tr>
              </thead>
              <tbody>
                {pillarBreakdown.map((pb, i) => {
                  const total =
                    (pb.pace ?? 0) + (pb.consistency ?? 0) + (pb.execution ?? 0) + (pb.robustness ?? 0) + (pb.adaptation ?? 0);
                  return (
                    <tr key={pb.session_id} className="border-b border-steel/5">
                      <td className="py-2 pr-4 font-telemetry text-chalk text-xs">
                        S{i + 1}
                      </td>
                      <td className={`py-2 px-2 text-right font-telemetry text-xs ${scoreColor(pb.pace)}`}>
                        {pb.pace?.toFixed(0) ?? '—'}
                      </td>
                      <td className={`py-2 px-2 text-right font-telemetry text-xs ${scoreColor(pb.consistency)}`}>
                        {pb.consistency?.toFixed(0) ?? '—'}
                      </td>
                      <td className={`py-2 px-2 text-right font-telemetry text-xs ${scoreColor(pb.execution)}`}>
                        {pb.execution?.toFixed(0) ?? '—'}
                      </td>
                      <td className={`py-2 px-2 text-right font-telemetry text-xs ${scoreColor(pb.robustness)}`}>
                        {pb.robustness?.toFixed(0) ?? '—'}
                      </td>
                      <td className={`py-2 px-2 text-right font-telemetry text-xs font-bold ${scoreColor(total)}`}>
                        {total.toFixed(0)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Grade Distribution ──────────────────────────── */}
      {summary?.grade_counts && Object.keys(summary.grade_counts).length > 0 && (
        <div className="bg-concrete border border-steel/20 p-4 mb-6">
          <h3 className="font-monument text-sm text-chalk mb-3">Grade Distribution</h3>
          <div className="flex gap-3">
            {Object.entries(summary.grade_counts)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([grade, count]) => (
                <div key={grade} className="text-center">
                  <span className={`font-monument text-xl block ${
                    grade === 'A' || grade === 'A+' ? 'text-acid-green' :
                    grade === 'B' ? 'text-gold' :
                    grade === 'C' ? 'text-marshal-yellow' :
                    'text-safety-red'
                  }`}>
                    {grade}
                  </span>
                  <span className="font-telemetry text-[10px] text-steel">×{count}</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Mini Lap Chart ─────────────────────────────────────── */

function MiniLapChart({ lapTimes, bestTime }: { lapTimes: LapTime[]; bestTime: number | null }) {
  const times = lapTimes.map((l) => l.time);
  const max = Math.max(...times);
  const min = Math.min(...times);
  const range = max - min || 1;

  return (
    <div className="flex items-end gap-[2px] h-16">
      {lapTimes.map((l) => {
        const isBest = bestTime != null && Math.abs(l.time - bestTime) < 0.001;
        const pct = 20 + ((l.time - min) / range) * 80;
        return (
          <div
            key={l.lap}
            className={`flex-1 min-w-[3px] max-w-[12px] transition-colors ${isBest ? 'bg-acid-green' : 'bg-steel/30'}`}
            style={{ height: `${100 - pct + 20}%` }}
            title={`Lap ${l.lap}: ${l.time.toFixed(3)}s`}
          />
        );
      })}
    </div>
  );
}
