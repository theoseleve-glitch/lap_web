'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useState, useCallback, useMemo, useEffect, useId } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

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

function gradeHex(grade: string): string {
  if (grade.startsWith('A')) return '#B6FF2E';
  if (grade.startsWith('B')) return '#FFD400';
  if (grade.startsWith('C')) return '#FF6A00';
  return '#FF2A2A';
}

/* ------------------------------------------------------------------ */
/*  Progression Chart (interactive)                                    */
/* ------------------------------------------------------------------ */

const PAD = { top: 16, right: 60, bottom: 48, left: 56 };

function ProgressionChart({ entries }: { entries: ProgressionEntry[] }) {
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (entries.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No progression data', w / 2, h / 2);
        return;
      }

      const chartW = w - PAD.left - PAD.right;
      const chartH = h - PAD.top - PAD.bottom;
      const maxScore = 100;

      const times = entries.map((e) => e.best_time);
      const minT = Math.min(...times);
      const maxT = Math.max(...times);
      const rangeT = maxT - minT || 1;

      const xOf = (i: number) =>
        entries.length === 1
          ? PAD.left + chartW / 2
          : PAD.left + (i / (entries.length - 1)) * chartW;
      const yScore = (s: number) => PAD.top + ((maxScore - s) / maxScore) * chartH;
      const yTime = (t: number) => PAD.top + ((t - minT) / rangeT) * chartH;

      // Compute hovered index
      let hovIdx = -1;
      if (hover) {
        hovIdx = Math.max(0, Math.min(entries.length - 1, Math.round(hover.nx * (entries.length - 1))));
      }

      // Horizontal grid
      ctx.strokeStyle = 'rgba(138,143,152,0.2)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const y = PAD.top + (i / 5) * chartH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + chartW, y);
        ctx.stroke();
      }

      // Left Y-axis labels (Score)
      ctx.font = '11px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#8A8F98';
      for (let i = 0; i <= 5; i++) {
        const y = PAD.top + (i / 5) * chartH;
        ctx.fillText((maxScore - (i / 5) * maxScore).toFixed(0), PAD.left - 8, y);
      }
      ctx.save();
      ctx.translate(14, PAD.top + chartH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#8A8F98';
      ctx.font = '11px "IBM Plex Mono", monospace';
      ctx.fillText('Score', 0, 0);
      ctx.restore();

      // Right Y-axis labels (Lap Time)
      ctx.textAlign = 'left';
      ctx.fillStyle = '#FF6A00';
      for (let i = 0; i <= 5; i++) {
        const y = PAD.top + (i / 5) * chartH;
        ctx.fillText(formatTime(minT + (i / 5) * rangeT), PAD.left + chartW + 8, y);
      }
      ctx.save();
      ctx.translate(w - 6, PAD.top + chartH / 2);
      ctx.rotate(Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#FF6A00';
      ctx.font = '11px "IBM Plex Mono", monospace';
      ctx.fillText('Lap Time', 0, 0);
      ctx.restore();

      // X-axis labels
      const maxXLabels = Math.min(entries.length, 10);
      const step = Math.max(1, Math.floor(entries.length / maxXLabels));
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#8A8F98';
      for (let i = 0; i < entries.length; i += step) {
        ctx.fillText(entries[i].date, xOf(i), PAD.top + chartH + 8);
      }

      // Score area fill
      if (entries.length > 1) {
        ctx.beginPath();
        ctx.moveTo(xOf(0), yScore(entries[0].score));
        for (let i = 1; i < entries.length; i++) ctx.lineTo(xOf(i), yScore(entries[i].score));
        ctx.lineTo(xOf(entries.length - 1), PAD.top + chartH);
        ctx.lineTo(xOf(0), PAD.top + chartH);
        ctx.closePath();
        ctx.fillStyle = 'rgba(182,255,46,0.10)';
        ctx.fill();
      }

      // Score line
      ctx.beginPath();
      ctx.moveTo(xOf(0), yScore(entries[0].score));
      for (let i = 1; i < entries.length; i++) ctx.lineTo(xOf(i), yScore(entries[i].score));
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Score dots
      for (let i = 0; i < entries.length; i++) {
        ctx.beginPath();
        ctx.arc(xOf(i), yScore(entries[i].score), 3, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
      }

      // Lap time dots
      for (let i = 0; i < entries.length; i++) {
        ctx.beginPath();
        ctx.arc(xOf(i), yTime(entries[i].best_time), 5, 0, Math.PI * 2);
        ctx.fillStyle = '#FF6A00';
        ctx.fill();
      }

      // Hover highlights
      if (hovIdx >= 0) {
        const x = xOf(hovIdx);

        // Score hover dot (enlarged)
        ctx.beginPath();
        ctx.arc(x, yScore(entries[hovIdx].score), 6, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Time hover dot (enlarged)
        ctx.beginPath();
        ctx.arc(x, yTime(entries[hovIdx].best_time), 7, 0, Math.PI * 2);
        ctx.fillStyle = '#FF6A00';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    },
    [entries],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (entries.length === 0) return null;
      const idx = Math.max(0, Math.min(entries.length - 1, Math.round(hover.nx * (entries.length - 1))));
      const e = entries[idx];
      return {
        header: `${e.date} — ${e.track_name}`,
        lines: [
          { label: 'Score', value: e.score.toFixed(1), color: '#B6FF2E' },
          { label: 'Lap Time', value: formatTime(e.best_time), color: '#FF6A00' },
          { label: 'Grade', value: e.grade, color: gradeHex(e.grade) },
        ],
      };
    },
    [entries],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [entries],
    padding: PAD,
    getTooltipData,
    crosshair: true,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full" style={{ height: 320 }} />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function DriverProgressionPage() {
  const fieldId = useId();
  const { id } = useParams<{ id: string }>();
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
            <label htmlFor={`${fieldId}-track`} className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1">
              Track
            </label>
            <select
              id={`${fieldId}-track`}
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
          <ProgressionChart entries={progression} />
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
