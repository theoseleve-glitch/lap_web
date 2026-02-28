'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useCallback, useMemo, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable, QueryError } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ── Types ──────────────────────────────────────────────── */

interface DriverDetail {
  driver_id: number;
  driver_name: string;
  session_count: number;
  personal_best_s: number | null;
  mean_score: number | null;
  has_profile: boolean;
  style_label: string | null;
  total_laps: number;
  profile?: {
    weight_kg: number | null;
    kart_class: string | null;
    experience_level: string | null;
    goals: string | null;
    pace_delta_mean_s: number | null;
    consistency_rating: number | null;
    aggression_index: number | null;
    smoothness_index: number | null;
    improvement_trend: string | null;
    wet_skill_proxy: number | null;
  } | null;
  progression?: ProgressionEntry[];
}

interface ProgressionEntry {
  session_id: string;
  session_date: string;
  track_name: string;
  total_score: number | null;
  n_laps: number;
  best_lap_time_s?: number | null;
  pace_delta_s?: number | null;
}

interface SessionRow {
  session_id: string;
  session_date: string;
  track_name: string;
  session_type: string | null;
  n_laps: number;
  best_lap_time_s: number | null;
  total_score: number | null;
  grade: string | null;
}

interface TrackEntry {
  track_id: string;
  track_name: string;
  session_count: number;
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(s: number | null): string {
  if (s == null) return 'text-steel';
  if (s >= 80) return 'text-acid-green';
  if (s >= 60) return 'text-marshal-yellow';
  if (s >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

/* ── Progression Chart ──────────────────────────────────── */

const PROG_PAD = { top: 15, right: 15, bottom: 30, left: 45 };

function ProgressionChart({ data }: { data: ProgressionEntry[] }) {
  const scored = useMemo(() => data.filter((d) => d.total_score != null), [data]);
  const { minScore, maxScore, range } = useMemo(() => {
    const scores = scored.map((d) => d.total_score!);
    const mn = Math.min(...scores);
    const mx = Math.max(...scores);
    return { minScore: mn, maxScore: mx, range: mx - mn || 1 };
  }, [scored]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (scored.length < 2) return;
      const plotW = w - PROG_PAD.left - PROG_PAD.right;
      const plotH = h - PROG_PAD.top - PROG_PAD.bottom;
      const n = scored.length;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = PROG_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(PROG_PAD.left, y);
        ctx.lineTo(PROG_PAD.left + plotW, y);
        ctx.stroke();
      }

      // Y-axis
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const val = maxScore - (i / 4) * range;
        ctx.fillText(val.toFixed(0), PROG_PAD.left - 5, PROG_PAD.top + (i / 4) * plotH + 3);
      }

      const hovIdx = hover ? Math.round(hover.nx * (n - 1)) : -1;

      // Line
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = PROG_PAD.left + (i / (n - 1 || 1)) * plotW;
        const y = PROG_PAD.top + plotH - ((scored[i].total_score! - minScore) / range) * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Points
      for (let i = 0; i < n; i++) {
        const x = PROG_PAD.left + (i / (n - 1 || 1)) * plotW;
        const y = PROG_PAD.top + plotH - ((scored[i].total_score! - minScore) / range) * plotH;
        ctx.beginPath();
        ctx.arc(x, y, i === hovIdx ? 5 : 2.5, 0, Math.PI * 2);
        ctx.fillStyle = i === hovIdx ? '#B6FF2E' : '#B6FF2EAA';
        ctx.fill();
      }

      // X dates
      ctx.textAlign = 'center';
      const step = Math.max(1, Math.floor(n / 6));
      for (let i = 0; i < n; i += step) {
        const x = PROG_PAD.left + (i / (n - 1 || 1)) * plotW;
        ctx.fillStyle = '#8A8F98';
        ctx.fillText(scored[i].session_date.slice(5), x, h - 8);
      }
    },
    [scored, minScore, maxScore, range],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const idx = Math.round(hover.nx * (scored.length - 1));
      if (idx < 0 || idx >= scored.length) return null;
      const d = scored[idx];
      return {
        header: d.session_date,
        lines: [
          { label: 'Track', value: d.track_name },
          { label: 'Score', value: d.total_score?.toFixed(1) ?? '—', color: '#B6FF2E' },
          { label: 'Laps', value: String(d.n_laps) },
        ],
      };
    },
    [scored],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [scored],
    padding: PROG_PAD,
    getTooltipData,
  });

  if (scored.length < 2) {
    return (
      <div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">
        Need 2+ scored sessions for progression chart
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-48" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

export default function DriverDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data: driver, isLoading, error, refetch } = useQuery({
    queryKey: ['driver', id],
    queryFn: () => api.get<DriverDetail>(`/drivers/${id}`),
  });

  useEffect(() => {
    if (driver) {
      document.title = `${driver.driver_name} | LAP Coach`;
    }
  }, [driver]);

  const { data: sessionsData } = useQuery({
    queryKey: ['driver', id, 'sessions'],
    queryFn: () => api.get<{ sessions: SessionRow[] }>(`/drivers/${id}/sessions`),
    enabled: !!driver,
  });

  const { data: tracksData } = useQuery({
    queryKey: ['driver', id, 'tracks'],
    queryFn: () => api.get<{ tracks: TrackEntry[] }>(`/drivers/${id}/tracks`),
    enabled: !!driver,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return <QueryError message="Couldn't load driver details." onRetry={() => refetch()} />;
  }

  if (!driver) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Driver not found</h2>
        <p className="text-steel font-body text-sm mb-4">This driver may have been deleted or the link is invalid.</p>
        <Link href="/app/drivers" className="text-pit-orange font-telemetry text-xs hover:underline">
          Back to drivers
        </Link>
      </div>
    );
  }

  const sessions = sessionsData?.sessions ?? [];
  const driverTracks = tracksData?.tracks ?? [];
  const progression = driver.progression ?? [];
  const profile = driver.profile;

  return (
    <div>
      <PageHeader
        title={driver.driver_name}
        subtitle={`${driver.session_count} sessions · ${driver.total_laps} laps`}
      />

      {/* ── Stats ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <StatCard label="Personal Best" value={fmtTime(driver.personal_best_s)} trend="up" />
        <StatCard label="Avg Score" value={driver.mean_score?.toFixed(1) ?? '—'} unit="/100" />
        <StatCard label="Sessions" value={driver.session_count} />
        <StatCard label="Total Laps" value={driver.total_laps} />
        <StatCard label="Style" value={driver.style_label ?? '—'} />
      </div>

      {/* ── Profile card ────────────────────────────────── */}
      {profile && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-5 mb-6">
          <h2 className="font-body text-chalk text-lg mb-3">Driver Profile</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {profile.weight_kg != null && (
              <div>
                <span className="text-steel/60 text-[10px] font-telemetry block">WEIGHT</span>
                <span className="text-chalk font-telemetry text-sm">{profile.weight_kg} kg</span>
              </div>
            )}
            {profile.kart_class && (
              <div>
                <span className="text-steel/60 text-[10px] font-telemetry block">CLASS</span>
                <span className="text-chalk font-telemetry text-sm">{profile.kart_class}</span>
              </div>
            )}
            {profile.experience_level && (
              <div>
                <span className="text-steel/60 text-[10px] font-telemetry block">EXPERIENCE</span>
                <span className="text-chalk font-telemetry text-sm">{profile.experience_level}</span>
              </div>
            )}
            {profile.improvement_trend && (
              <div>
                <span className="text-steel/60 text-[10px] font-telemetry block">TREND</span>
                <span className={`font-telemetry text-sm ${
                  profile.improvement_trend === 'up' ? 'text-acid-green' :
                  profile.improvement_trend === 'down' ? 'text-safety-red' : 'text-steel'
                }`}>
                  {profile.improvement_trend === 'up' ? '↑ Improving' :
                   profile.improvement_trend === 'down' ? '↓ Declining' : '→ Stable'}
                </span>
              </div>
            )}
            {profile.pace_delta_mean_s != null && (
              <div>
                <span className="text-steel/60 text-[10px] font-telemetry block">PACE DELTA</span>
                <span className={`font-telemetry text-sm ${profile.pace_delta_mean_s < 0 ? 'text-acid-green' : 'text-safety-red'}`}>
                  {profile.pace_delta_mean_s > 0 ? '+' : ''}{profile.pace_delta_mean_s.toFixed(3)}s
                </span>
              </div>
            )}
            {profile.consistency_rating != null && (
              <div>
                <span className="text-steel/60 text-[10px] font-telemetry block">CONSISTENCY</span>
                <span className="text-chalk font-telemetry text-sm">{profile.consistency_rating.toFixed(1)}/10</span>
              </div>
            )}
            {profile.wet_skill_proxy != null && (
              <div>
                <span className="text-steel/60 text-[10px] font-telemetry block">WET SKILL</span>
                <span className="text-chalk font-telemetry text-sm">{(profile.wet_skill_proxy * 100).toFixed(0)}%</span>
              </div>
            )}
            {profile.goals && (
              <div className="col-span-2">
                <span className="text-steel/60 text-[10px] font-telemetry block">GOALS</span>
                <span className="text-chalk font-body text-sm">{profile.goals}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Progression Chart ───────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <ChartPanel title="Score Progression" subtitle="Score trend over sessions">
          <ProgressionChart data={progression.length > 0 ? progression : sessions.map((s) => ({
            session_id: s.session_id,
            session_date: s.session_date,
            track_name: s.track_name,
            total_score: s.total_score,
            n_laps: s.n_laps,
          }))} />
        </ChartPanel>

        {/* Tracks driven */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-5">
          <h3 className="font-body text-chalk text-sm mb-3">Tracks Driven</h3>
          {driverTracks.length === 0 ? (
            <p className="text-steel font-telemetry text-xs">No track data</p>
          ) : (
            <div className="space-y-2">
              {driverTracks.map((t) => (
                <Link
                  key={t.track_id}
                  href={`/app/tracks/${t.track_id}`}
                  className="w-full flex items-center justify-between py-1.5 px-2 rounded hover:bg-asphalt/50 transition-colors"
                >
                  <span className="text-chalk font-body text-sm">{t.track_name}</span>
                  <span className="text-steel font-telemetry text-xs">{t.session_count} sessions</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Session History ──────────────────────────────── */}
      {sessions.length > 0 && (
        <div>
          <h2 className="font-body text-chalk text-lg mb-3">Session History</h2>
          <DataTable
            columns={[
              { key: 'session_date', header: 'Date', sortable: true, className: 'font-telemetry' },
              { key: 'track_name', header: 'Track', sortable: true },
              {
                key: 'session_type',
                header: 'Type',
                render: (row: SessionRow) => (
                  <span className="text-steel/60 font-telemetry text-xs uppercase">
                    {row.session_type ?? '—'}
                  </span>
                ),
              },
              {
                key: 'n_laps',
                header: 'Laps',
                className: 'font-telemetry text-right',
              },
              {
                key: 'best_lap_time_s',
                header: 'Best Lap',
                sortable: true,
                className: 'font-telemetry',
                render: (row: SessionRow) => (
                  <span className="text-acid-green">{fmtTime(row.best_lap_time_s)}</span>
                ),
              },
              {
                key: 'total_score',
                header: 'Score',
                sortable: true,
                className: 'font-telemetry text-right',
                render: (row: SessionRow) => (
                  <span className={scoreColor(row.total_score)}>
                    {row.total_score?.toFixed(1) ?? '—'}
                  </span>
                ),
              },
              {
                key: 'grade',
                header: 'Grade',
                render: (row: SessionRow) => (
                  <span className={`font-monument ${scoreColor(row.total_score)}`}>
                    {row.grade ?? '—'}
                  </span>
                ),
              },
            ]}
            data={sessions}
            keyField="session_id"
            onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
          />
        </div>
      )}
    </div>
  );
}
