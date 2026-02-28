'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useCallback, useMemo, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable, QueryError, SkeletonStatCards, SkeletonBox, SkeletonTableRows } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ── Types ──────────────────────────────────────────────── */

interface TrackDetail {
  track_id: string;
  track_name: string;
  lap_length_m: number | null;
  lap_count: number | null;
  start_lat: number | null;
  start_lon: number | null;
  session_count: number;
  best_time_s: number | null;
  driver_count: number;
  has_joker: number | null;
}

interface LeaderboardEntry {
  rank: number;
  session_id: string;
  session_date: string;
  best_lap_time_s: number;
  total_score: number | null;
  grade: string | null;
  session_type: string | null;
  track_state: string | null;
  driver_name: string;
}

interface EvolutionSession {
  session_id: string;
  date: string;
  best_time_s: number;
  score: number | null;
  track_state: string | null;
  session_type: string | null;
  driver: string;
}

interface GeometryData {
  track_name: string;
  latitudes: number[];
  longitudes: number[];
}

interface RecordEntry {
  id: number;
  record_time_s: number;
  record_holder: string | null;
  record_date: string | null;
  vehicle_class: string | null;
  source: string | null;
}

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function fmtLength(m: number | null): string {
  if (m == null || m <= 0) return '—';
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}

function scoreColor(s: number | null): string {
  if (s == null) return 'text-steel';
  if (s >= 80) return 'text-acid-green';
  if (s >= 60) return 'text-marshal-yellow';
  if (s >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}

const STATE_COLORS: Record<string, string> = {
  dry: '#B6FF2E',
  wet: '#60A5FA',
  damp: '#FFD400',
  mixed: '#A78BFA',
  greasy: '#FF6A00',
};

/* ── Evolution Chart ────────────────────────────────────── */

const EVO_PAD = { top: 15, right: 15, bottom: 30, left: 55 };

function EvolutionChart({ sessions }: { sessions: EvolutionSession[] }) {
  const { minTime, maxTime, timeRange } = useMemo(() => {
    const times = sessions.map((s) => s.best_time_s);
    const mn = Math.min(...times);
    const mx = Math.max(...times);
    return { minTime: mn, maxTime: mx, timeRange: mx - mn || 1 };
  }, [sessions]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (sessions.length === 0) return;
      const plotW = w - EVO_PAD.left - EVO_PAD.right;
      const plotH = h - EVO_PAD.top - EVO_PAD.bottom;
      const n = sessions.length;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = EVO_PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(EVO_PAD.left, y);
        ctx.lineTo(EVO_PAD.left + plotW, y);
        ctx.stroke();
      }

      // Y-axis
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const val = maxTime - (i / 4) * timeRange;
        const m = Math.floor(val / 60);
        const s = (val % 60).toFixed(1);
        ctx.fillText(`${m}:${s.padStart(4, '0')}`, EVO_PAD.left - 5, EVO_PAD.top + (i / 4) * plotH + 3);
      }

      // X-axis dates
      ctx.textAlign = 'center';
      const step = Math.max(1, Math.floor(n / 6));
      for (let i = 0; i < n; i += step) {
        const x = EVO_PAD.left + (i / (n - 1 || 1)) * plotW;
        const date = sessions[i].date.slice(5); // MM-DD
        ctx.fillText(date, x, h - 8);
      }

      // Hover
      const hoveredIdx = hover ? Math.round(hover.nx * (n - 1)) : -1;
      if (hoveredIdx >= 0 && hoveredIdx < n) {
        const hx = EVO_PAD.left + (hoveredIdx / (n - 1 || 1)) * plotW;
        ctx.strokeStyle = 'rgba(243, 240, 232, 0.2)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hx, EVO_PAD.top);
        ctx.lineTo(hx, EVO_PAD.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Line
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = EVO_PAD.left + (i / (n - 1 || 1)) * plotW;
        const y = EVO_PAD.top + plotH - ((sessions[i].best_time_s - minTime) / timeRange) * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Points
      for (let i = 0; i < n; i++) {
        const x = EVO_PAD.left + (i / (n - 1 || 1)) * plotW;
        const y = EVO_PAD.top + plotH - ((sessions[i].best_time_s - minTime) / timeRange) * plotH;
        const isHov = i === hoveredIdx;
        const state = sessions[i].track_state ?? 'dry';
        ctx.beginPath();
        ctx.arc(x, y, isHov ? 5 : 3, 0, Math.PI * 2);
        ctx.fillStyle = STATE_COLORS[state] ?? '#B6FF2E';
        ctx.fill();
        if (isHov) {
          ctx.strokeStyle = '#F3F0E8';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      // Running best line
      let best = sessions[0].best_time_s;
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        best = Math.min(best, sessions[i].best_time_s);
        const x = EVO_PAD.left + (i / (n - 1 || 1)) * plotW;
        const y = EVO_PAD.top + plotH - ((best - minTime) / timeRange) * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#FFD40060';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    },
    [sessions, minTime, maxTime, timeRange],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const n = sessions.length;
      const idx = Math.round(hover.nx * (n - 1));
      if (idx < 0 || idx >= n) return null;
      const s = sessions[idx];
      return {
        header: s.date,
        lines: [
          { label: 'Driver', value: s.driver },
          { label: 'Best', value: fmtTime(s.best_time_s), color: '#B6FF2E' },
          { label: 'Score', value: s.score?.toFixed(1) ?? '—' },
          { label: 'Condition', value: s.track_state ?? 'dry', color: STATE_COLORS[s.track_state ?? 'dry'] },
        ],
      };
    },
    [sessions],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [sessions],
    padding: EVO_PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-56" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Track Map (canvas GPS plot) ────────────────────────── */

const MAP_PAD = { top: 10, right: 10, bottom: 10, left: 10 };

function TrackMapChart({ geometry }: { geometry: GeometryData }) {
  const { latMin, latRange, lonMin, lonRange } = useMemo(() => {
    const lats = geometry.latitudes;
    const lons = geometry.longitudes;
    const latMn = Math.min(...lats);
    const latMx = Math.max(...lats);
    const lonMn = Math.min(...lons);
    const lonMx = Math.max(...lons);
    return { latMin: latMn, latRange: latMx - latMn || 0.001, lonMin: lonMn, lonRange: lonMx - lonMn || 0.001 };
  }, [geometry]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      ctx.clearRect(0, 0, w, h);
      const plotW = w - MAP_PAD.left - MAP_PAD.right;
      const plotH = h - MAP_PAD.top - MAP_PAD.bottom;
      const { latitudes, longitudes } = geometry;
      const n = latitudes.length;
      if (n < 2) return;

      // Maintain aspect ratio
      const latScale = plotH / latRange;
      const lonScale = plotW / lonRange;
      const scale = Math.min(latScale, lonScale);
      const offX = MAP_PAD.left + (plotW - lonRange * scale) / 2;
      const offY = MAP_PAD.top + (plotH - latRange * scale) / 2;

      // Draw track outline
      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = offX + (longitudes[i] - lonMin) * scale;
        const y = offY + plotH - (latitudes[i] - latMin) * scale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Start/finish marker
      const sx = offX + (longitudes[0] - lonMin) * scale;
      const sy = offY + plotH - (latitudes[0] - latMin) * scale;
      ctx.beginPath();
      ctx.arc(sx, sy, 5, 0, Math.PI * 2);
      ctx.fillStyle = '#FF6A00';
      ctx.fill();
      ctx.strokeStyle = '#F3F0E8';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // S/F label
      ctx.fillStyle = '#FF6A00';
      ctx.font = 'bold 9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText('S/F', sx + 8, sy + 3);
    },
    [geometry, latMin, latRange, lonMin, lonRange],
  );

  const { canvasRef, containerRef } = useInteractiveCanvas({
    draw,
    deps: [geometry],
    padding: MAP_PAD,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-56" />
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

export default function TrackDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data: track, isLoading, error, refetch } = useQuery({
    queryKey: ['track', id],
    queryFn: () => api.get<TrackDetail>(`/tracks/${id}`),
  });

  useEffect(() => {
    if (track) {
      document.title = `${track.track_name} | LAP Coach`;
    }
  }, [track]);

  const { data: leaderboardData } = useQuery({
    queryKey: ['track', id, 'leaderboard'],
    queryFn: () => api.get<{ leaderboard: LeaderboardEntry[] }>(`/tracks/${id}/leaderboard`),
    enabled: !!track,
  });

  const { data: evolutionData } = useQuery({
    queryKey: ['track', id, 'evolution'],
    queryFn: () => api.get<{ sessions: EvolutionSession[] }>(`/tracks/${id}/evolution`),
    enabled: !!track,
  });

  const { data: geometryData } = useQuery({
    queryKey: ['track', id, 'geometry'],
    queryFn: () => api.get<GeometryData>(`/tracks/${id}/geometry`),
    enabled: !!track,
  });

  const { data: recordsData } = useQuery({
    queryKey: ['track', id, 'records'],
    queryFn: () => api.get<{ records: RecordEntry[] }>(`/tracks/${id}/records`),
    enabled: !!track,
  });

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-48 mb-2" />
          <SkeletonBox className="h-3 w-28" />
        </div>
        <SkeletonStatCards count={4} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <SkeletonBox className="h-3 w-24 mb-3" />
            <SkeletonBox className="h-48 w-full" />
          </div>
          <div className="bg-concrete rounded-lg border border-steel/20 p-4">
            <SkeletonBox className="h-3 w-24 mb-3" />
            <SkeletonBox className="h-48 w-full" />
          </div>
        </div>
        <SkeletonTableRows rows={5} cols={5} />
      </div>
    );
  }

  if (error) {
    return <QueryError message="Couldn't load track details." onRetry={() => refetch()} />;
  }

  if (!track) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Track not found</h2>
        <p className="text-steel font-body text-sm mb-4">This track may have been deleted or the link is invalid.</p>
        <Link href="/app/tracks" className="text-pit-orange font-telemetry text-xs hover:underline">
          Back to tracks
        </Link>
      </div>
    );
  }

  const leaderboard = leaderboardData?.leaderboard ?? [];
  const evolution = evolutionData?.sessions ?? [];
  const geometry = geometryData;
  const records = recordsData?.records ?? [];

  return (
    <div>
      <PageHeader
        title={track.track_name}
        subtitle={fmtLength(track.lap_length_m)}
        actions={
          <Link
            href="/app/tracks"
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            ← All Tracks
          </Link>
        }
      />

      {/* ── Stat Cards ──────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <StatCard label="Track Record" value={fmtTime(track.best_time_s)} trend="up" />
        <StatCard label="Sessions" value={track.session_count} />
        <StatCard label="Drivers" value={track.driver_count ?? 0} />
        <StatCard label="Lap Length" value={fmtLength(track.lap_length_m)} />
        {track.has_joker ? (
          <StatCard label="Joker Lap" value="Yes" />
        ) : (
          <StatCard label="Total Laps" value={track.lap_count ?? 0} />
        )}
      </div>

      {/* ── GPS Coordinates ─────────────────────────────── */}
      {track.start_lat != null && track.start_lon != null && (
        <div className="flex items-center gap-3 mb-6 text-steel/40 font-telemetry text-[10px]">
          <span>S/F: {track.start_lat.toFixed(6)}, {track.start_lon.toFixed(6)}</span>
        </div>
      )}

      {/* ── Charts Row ──────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <ChartPanel title="Lap Time Evolution" subtitle="Best lap progression over sessions">
          {evolution.length >= 2 ? (
            <EvolutionChart sessions={evolution} />
          ) : (
            <div className="h-56 flex items-center justify-center text-steel font-telemetry text-xs">
              Need 2+ sessions for evolution chart
            </div>
          )}
        </ChartPanel>

        <ChartPanel title="Track Layout" subtitle="GPS reference line">
          {geometry && geometry.latitudes?.length > 1 ? (
            <TrackMapChart geometry={geometry} />
          ) : (
            <div className="h-56 flex items-center justify-center text-steel font-telemetry text-xs">
              No GPS geometry available
            </div>
          )}
        </ChartPanel>
      </div>

      {/* ── Track Records (Podium) ──────────────────────── */}
      {records.length > 0 && (
        <div className="mb-6">
          <h2 className="font-body text-chalk text-lg mb-4">Track Records</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {records.slice(0, 3).map((r, i) => {
              const medals = ['🥇', '🥈', '🥉'];
              const borderColors = ['border-marshal-yellow/40', 'border-steel/30', 'border-pit-orange/30'];
              return (
                <div key={r.id} className={`bg-concrete rounded-lg border ${borderColors[i]} p-4 text-center`}>
                  <span className="text-2xl">{medals[i]}</span>
                  <p className="font-monument text-xl text-chalk mt-1">{fmtTime(r.record_time_s)}</p>
                  <p className="text-steel font-telemetry text-xs mt-1">
                    {r.record_holder ?? 'Unknown'}
                  </p>
                  <div className="flex items-center justify-center gap-2 mt-1 text-steel/40 font-telemetry text-[10px]">
                    {r.record_date && <span>{r.record_date}</span>}
                    {r.vehicle_class && <span>• {r.vehicle_class}</span>}
                  </div>
                </div>
              );
            })}
          </div>
          {records.length > 3 && (
            <div className="mt-3 bg-concrete rounded-lg border border-steel/20 overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-steel/20">
                    <th scope="col" className="px-4 py-2 text-left text-steel font-telemetry text-xs uppercase">#</th>
                    <th scope="col" className="px-4 py-2 text-left text-steel font-telemetry text-xs uppercase">Time</th>
                    <th scope="col" className="px-4 py-2 text-left text-steel font-telemetry text-xs uppercase">Holder</th>
                    <th scope="col" className="px-4 py-2 text-left text-steel font-telemetry text-xs uppercase">Date</th>
                    <th scope="col" className="px-4 py-2 text-left text-steel font-telemetry text-xs uppercase">Class</th>
                  </tr>
                </thead>
                <tbody>
                  {records.slice(3).map((r, i) => (
                    <tr key={r.id} className="border-b border-steel/10">
                      <td className="px-4 py-2 text-steel font-telemetry text-sm">{i + 4}</td>
                      <td className="px-4 py-2 text-acid-green font-telemetry text-sm">{fmtTime(r.record_time_s)}</td>
                      <td className="px-4 py-2 text-chalk font-body text-sm">{r.record_holder ?? '—'}</td>
                      <td className="px-4 py-2 text-steel font-telemetry text-sm">{r.record_date ?? '—'}</td>
                      <td className="px-4 py-2 text-steel font-telemetry text-sm">{r.vehicle_class ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Leaderboard ─────────────────────────────────── */}
      {leaderboard.length > 0 && (
        <div className="mb-6">
          <h2 className="font-body text-chalk text-lg mb-4">Leaderboard</h2>
          <DataTable
            columns={[
              {
                key: 'rank',
                header: '#',
                className: 'font-telemetry w-12',
                render: (row: LeaderboardEntry) => (
                  <span className={row.rank <= 3 ? 'text-marshal-yellow font-monument' : 'text-steel'}>
                    {row.rank}
                  </span>
                ),
              },
              { key: 'driver_name', header: 'Driver', sortable: true },
              {
                key: 'best_lap_time_s',
                header: 'Best Lap',
                sortable: true,
                className: 'font-telemetry',
                render: (row: LeaderboardEntry) => (
                  <span className="text-acid-green">{fmtTime(row.best_lap_time_s)}</span>
                ),
              },
              {
                key: 'total_score',
                header: 'Score',
                className: 'font-telemetry text-right',
                render: (row: LeaderboardEntry) => (
                  <span className={scoreColor(row.total_score)}>
                    {row.total_score?.toFixed(1) ?? '—'}
                  </span>
                ),
              },
              {
                key: 'grade',
                header: 'Grade',
                className: 'font-telemetry',
                render: (row: LeaderboardEntry) => (
                  <span className={`font-monument ${scoreColor(row.total_score)}`}>{row.grade ?? '—'}</span>
                ),
              },
              {
                key: 'track_state',
                header: 'Condition',
                render: (row: LeaderboardEntry) => {
                  const st = row.track_state;
                  if (!st) return <span className="text-steel/40">—</span>;
                  const color = STATE_COLORS[st] ?? '#8A8F98';
                  return (
                    <span
                      className="inline-flex px-2 py-0.5 rounded text-[10px] font-telemetry uppercase"
                      style={{ backgroundColor: color + '18', color }}
                    >
                      {st}
                    </span>
                  );
                },
              },
              {
                key: 'session_date',
                header: 'Date',
                sortable: true,
                className: 'font-telemetry',
              },
            ]}
            data={leaderboard}
            keyField="rank"
            onRowClick={(row) => router.push(`/app/sessions/${row.session_id}`)}
          />
        </div>
      )}
    </div>
  );
}
