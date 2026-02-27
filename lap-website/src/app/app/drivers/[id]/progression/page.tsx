'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable } from '@/components/app';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ProgressionEntry {
  date: string;
  track_name: string;
  score: number;
  best_time: number;
  grade: string;
}

interface ProgressionResponse {
  driver_name: string;
  best_score: number;
  current_streak: number;
  total_improvement: number;
  fastest_track: string;
  progression: ProgressionEntry[];
}

interface TrackOption {
  id: number;
  name: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatTime(s: number | null): string {
  if (s == null) return '\u2014';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function gradeColor(grade: string): string {
  if (grade.startsWith('A')) return 'text-acid-green';
  if (grade.startsWith('B')) return 'text-marshal-yellow';
  if (grade.startsWith('C')) return 'text-pit-orange';
  return 'text-safety-red';
}

/* ------------------------------------------------------------------ */
/*  Canvas draw                                                        */
/* ------------------------------------------------------------------ */

const STEEL = 'rgba(138,143,152,1)';
const STEEL_20 = 'rgba(138,143,152,0.2)';
const ACID_GREEN = '#B6FF2E';
const ACID_GREEN_10 = 'rgba(182,255,46,0.10)';
const PIT_ORANGE = '#FF6A00';

function drawProgressionChart(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  entries: ProgressionEntry[],
) {
  ctx.clearRect(0, 0, w, h);

  if (entries.length === 0) {
    ctx.fillStyle = STEEL;
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No progression data', w / 2, h / 2);
    return;
  }

  /* Padding */
  const padL = 56;
  const padR = 60;
  const padT = 16;
  const padB = 48;
  const chartW = w - padL - padR;
  const chartH = h - padT - padB;

  /* Score range: always 0-100 */
  const minScore = 0;
  const maxScore = 100;

  /* Lap time range */
  const times = entries.map((e) => e.best_time);
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rangeT = maxT - minT || 1;

  /* X-axis: evenly spaced by index */
  const xOf = (i: number) =>
    entries.length === 1
      ? padL + chartW / 2
      : padL + (i / (entries.length - 1)) * chartW;

  const yScore = (s: number) =>
    padT + ((maxScore - s) / (maxScore - minScore)) * chartH;

  const yTime = (t: number) =>
    padT + ((t - minT) / rangeT) * chartH;

  /* Horizontal grid */
  const gridRows = 5;
  ctx.strokeStyle = STEEL_20;
  ctx.lineWidth = 1;
  for (let i = 0; i <= gridRows; i++) {
    const y = padT + (i / gridRows) * chartH;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + chartW, y);
    ctx.stroke();
  }

  /* Left Y-axis labels (Score) */
  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = STEEL;
  for (let i = 0; i <= gridRows; i++) {
    const y = padT + (i / gridRows) * chartH;
    const val = maxScore - (i / gridRows) * (maxScore - minScore);
    ctx.fillText(val.toFixed(0), padL - 8, y);
  }
  /* Left axis title */
  ctx.save();
  ctx.translate(14, padT + chartH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = STEEL;
  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.fillText('Score', 0, 0);
  ctx.restore();

  /* Right Y-axis labels (Lap Time) */
  ctx.textAlign = 'left';
  ctx.fillStyle = PIT_ORANGE;
  for (let i = 0; i <= gridRows; i++) {
    const y = padT + (i / gridRows) * chartH;
    const val = minT + (i / gridRows) * rangeT;
    ctx.fillText(formatTime(val), padL + chartW + 8, y);
  }
  /* Right axis title */
  ctx.save();
  ctx.translate(w - 6, padT + chartH / 2);
  ctx.rotate(Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = PIT_ORANGE;
  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.fillText('Lap Time', 0, 0);
  ctx.restore();

  /* X-axis labels */
  const maxXLabels = Math.min(entries.length, 10);
  const step = Math.max(1, Math.floor(entries.length / maxXLabels));
  ctx.font = '10px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillStyle = STEEL;
  for (let i = 0; i < entries.length; i += step) {
    ctx.fillText(entries[i].date, xOf(i), padT + chartH + 8);
  }

  /* Score area fill */
  if (entries.length > 1) {
    ctx.beginPath();
    ctx.moveTo(xOf(0), yScore(entries[0].score));
    for (let i = 1; i < entries.length; i++) {
      ctx.lineTo(xOf(i), yScore(entries[i].score));
    }
    ctx.lineTo(xOf(entries.length - 1), padT + chartH);
    ctx.lineTo(xOf(0), padT + chartH);
    ctx.closePath();
    ctx.fillStyle = ACID_GREEN_10;
    ctx.fill();
  }

  /* Score line */
  ctx.beginPath();
  ctx.moveTo(xOf(0), yScore(entries[0].score));
  for (let i = 1; i < entries.length; i++) {
    ctx.lineTo(xOf(i), yScore(entries[i].score));
  }
  ctx.strokeStyle = ACID_GREEN;
  ctx.lineWidth = 2;
  ctx.stroke();

  /* Score dots (small, on the line) */
  for (let i = 0; i < entries.length; i++) {
    ctx.beginPath();
    ctx.arc(xOf(i), yScore(entries[i].score), 3, 0, Math.PI * 2);
    ctx.fillStyle = ACID_GREEN;
    ctx.fill();
  }

  /* Lap time dots */
  for (let i = 0; i < entries.length; i++) {
    ctx.beginPath();
    ctx.arc(xOf(i), yTime(entries[i].best_time), 5, 0, Math.PI * 2);
    ctx.fillStyle = PIT_ORANGE;
    ctx.fill();
  }
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function DriverProgressionPage() {
  const { id } = useParams<{ id: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [trackId, setTrackId] = useState('');

  const queryPath = trackId
    ? `/drivers/${id}/progression?track_id=${trackId}`
    : `/drivers/${id}/progression`;

  const { data, isLoading, error } = useQuery({
    queryKey: ['driver-progression', id, trackId],
    queryFn: () => api.get<ProgressionResponse>(queryPath),
  });

  const { data: tracks } = useQuery({
    queryKey: ['driver-tracks', id],
    queryFn: () => api.get<{ tracks: TrackOption[] }>(`/drivers/${id}/tracks`),
  });

  const trackOptions = useMemo(() => tracks?.tracks ?? [], [tracks]);

  useEffect(() => {
    if (trackId || trackOptions.length === 0) return;
    setTrackId(String(trackOptions[0].id));
  }, [trackId, trackOptions]);

  const draw = useCallback(() => {
    if (!data || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    drawProgressionChart(ctx, rect.width, rect.height, data.progression);
  }, [data]);

  useEffect(() => {
    draw();
  }, [draw]);

  /* Redraw on window resize */
  useEffect(() => {
    const onResize = () => draw();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [draw]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) return <div className="text-steel font-body">Driver not found</div>;

  const progression = data.progression ?? [];

  return (
    <div>
      <PageHeader
        title={data.driver_name}
        subtitle="Progression"
        actions={
          <div>
            <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1">
              Track
            </label>
            <select
              value={trackId}
              onChange={(e) => setTrackId(e.target.value)}
              className="bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
            >
              <option value="">All Tracks</option>
              {trackOptions.map((t) => (
                <option key={t.id} value={String(t.id)}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          label="Best Score"
          value={data.best_score.toFixed(1)}
          unit="/100"
          trend="up"
        />
        <StatCard
          label="Current Streak"
          value={data.current_streak}
          unit="sessions"
        />
        <StatCard
          label="Total Improvement"
          value={`${data.total_improvement > 0 ? '+' : ''}${data.total_improvement.toFixed(1)}`}
          unit="pts"
          trend={data.total_improvement > 0 ? 'up' : data.total_improvement < 0 ? 'down' : 'neutral'}
        />
        <StatCard label="Fastest Track" value={data.fastest_track ?? '\u2014'} />
      </div>

      {/* Progression chart */}
      <div className="mb-6">
        <ChartPanel
          title="Score & Lap Time Progression"
          subtitle="Dual-axis: score (green line) and lap time (orange dots)"
          loading={isLoading}
          error={error?.message ?? null}
        >
          <canvas
            ref={canvasRef}
            className="w-full"
            style={{ height: 320 }}
          />
        </ChartPanel>
      </div>

      {/* Data table */}
      {progression.length > 0 && (
        <div>
          <h2 className="font-body text-chalk text-lg mb-3">Session History</h2>
          <DataTable
            columns={[
              {
                key: 'date',
                header: 'Date',
                sortable: true,
                className: 'font-telemetry',
              },
              {
                key: 'track_name',
                header: 'Track',
                sortable: true,
              },
              {
                key: 'score',
                header: 'Score',
                sortable: true,
                className: 'font-telemetry',
                render: (row: ProgressionEntry) => (
                  <span className="text-acid-green">{row.score.toFixed(1)}</span>
                ),
              },
              {
                key: 'best_time',
                header: 'Best Lap',
                sortable: true,
                className: 'font-telemetry',
                render: (row: ProgressionEntry) => (
                  <span className="text-pit-orange">{formatTime(row.best_time)}</span>
                ),
              },
              {
                key: 'grade',
                header: 'Grade',
                sortable: true,
                className: 'font-telemetry',
                render: (row: ProgressionEntry) => (
                  <span className={gradeColor(row.grade)}>{row.grade}</span>
                ),
              },
            ]}
            data={progression}
            keyField="date"
          />
        </div>
      )}
    </div>
  );
}
