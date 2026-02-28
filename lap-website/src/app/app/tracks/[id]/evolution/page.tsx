'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useState, useCallback, useRef } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface EvolutionEntry {
  date: string;
  driver_name: string;
  best_time: number;
  delta_to_record: number;
}

interface EvolutionResponse {
  track_name: string;
  record_time: number;
  record_holder: string;
  sessions_count: number;
  improvement_pct: number;
  evolution: EvolutionEntry[];
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

function formatDelta(s: number): string {
  if (s === 0) return '\u2014';
  return `+${s.toFixed(3)}`;
}

/* ------------------------------------------------------------------ */
/*  Evolution Chart (interactive with ref-bridge)                      */
/* ------------------------------------------------------------------ */

const PAD = { top: 16, right: 20, bottom: 48, left: 64 };

interface ScreenPoint {
  x: number;
  y: number;
  entry: EvolutionEntry;
  isRecord: boolean;
}

function EvolutionChart({ entries }: { entries: EvolutionEntry[] }) {
  const pointsRef = useRef<ScreenPoint[]>([]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (entries.length === 0) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No evolution data', w / 2, h / 2);
        return;
      }

      const chartW = w - PAD.left - PAD.right;
      const chartH = h - PAD.top - PAD.bottom;

      const times = entries.map((e) => e.best_time);
      const minT = Math.min(...times);
      const maxT = Math.max(...times);
      const rangeT = maxT - minT || 1;

      const dates = entries.map((e) => new Date(e.date).getTime());
      const minDate = Math.min(...dates);
      const maxDate = Math.max(...dates);
      const rangeDate = maxDate - minDate || 1;

      const xOf = (d: number) => PAD.left + ((d - minDate) / rangeDate) * chartW;
      const yOf = (t: number) => PAD.top + ((t - minT) / rangeT) * chartH;

      // Grid
      ctx.strokeStyle = 'rgba(138,143,152,0.2)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const y = PAD.top + (i / 5) * chartH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + chartW, y);
        ctx.stroke();

        const val = minT + (i / 5) * rangeT;
        ctx.fillStyle = '#8A8F98';
        ctx.font = '11px "IBM Plex Mono", monospace';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(formatTime(val), PAD.left - 8, y);
      }

      // X-axis labels
      const uniqueDates = Array.from(new Set(entries.map((e) => e.date))).sort();
      const maxXLabels = Math.min(uniqueDates.length, 8);
      const step = Math.max(1, Math.floor(uniqueDates.length / maxXLabels));
      ctx.font = '11px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = '#8A8F98';
      for (let i = 0; i < uniqueDates.length; i += step) {
        const d = new Date(uniqueDates[i]).getTime();
        ctx.fillText(uniqueDates[i], xOf(d), PAD.top + chartH + 8);
      }

      // Sort chronologically and compute record progression
      const sorted = [...entries].sort(
        (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
      );
      let runningMin = Infinity;
      const recordPoints: { x: number; y: number }[] = [];
      const isRecordArr: boolean[] = [];

      for (const entry of sorted) {
        if (entry.best_time < runningMin) {
          runningMin = entry.best_time;
          isRecordArr.push(true);
          recordPoints.push({ x: xOf(new Date(entry.date).getTime()), y: yOf(entry.best_time) });
        } else {
          isRecordArr.push(false);
        }
      }

      // Store screen points for ref-bridge hover detection
      const pts: ScreenPoint[] = sorted.map((entry, i) => ({
        x: xOf(new Date(entry.date).getTime()),
        y: yOf(entry.best_time),
        entry,
        isRecord: isRecordArr[i],
      }));
      pointsRef.current = pts;

      // Find hovered point
      let hovIdx = -1;
      if (hover) {
        let bestDist = Infinity;
        for (let i = 0; i < pts.length; i++) {
          const d = (pts[i].x - hover.x) ** 2 + (pts[i].y - hover.y) ** 2;
          if (d < bestDist) { bestDist = d; hovIdx = i; }
        }
        if (bestDist > 900) hovIdx = -1; // 30px radius
      }

      // Non-record dots (steel)
      sorted.forEach((_, i) => {
        if (isRecordArr[i]) return;
        const isHov = hovIdx === i;
        ctx.beginPath();
        ctx.arc(pts[i].x, pts[i].y, isHov ? 8 : 6, 0, Math.PI * 2);
        ctx.fillStyle = isHov ? '#F3F0E8' : '#8A8F98';
        ctx.fill();
        if (isHov) {
          ctx.strokeStyle = '#8A8F98';
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      });

      // Record progression line
      if (recordPoints.length > 1) {
        ctx.beginPath();
        ctx.moveTo(recordPoints[0].x, recordPoints[0].y);
        for (let i = 1; i < recordPoints.length; i++) ctx.lineTo(recordPoints[i].x, recordPoints[i].y);
        ctx.strokeStyle = '#B6FF2E';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Record dots (acid-green)
      sorted.forEach((_, i) => {
        if (!isRecordArr[i]) return;
        const isHov = hovIdx === i;
        ctx.beginPath();
        ctx.arc(pts[i].x, pts[i].y, isHov ? 8 : 6, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        if (isHov) {
          ctx.strokeStyle = '#F3F0E8';
          ctx.lineWidth = 2;
          ctx.stroke();
        }
      });
    },
    [entries],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const pts = pointsRef.current;
      if (pts.length === 0) return null;
      let nearest = -1, bestDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = (pts[i].x - hover.x) ** 2 + (pts[i].y - hover.y) ** 2;
        if (d < bestDist) { bestDist = d; nearest = i; }
      }
      if (nearest < 0 || bestDist > 900) return null;
      const pt = pts[nearest];
      return {
        header: `${pt.entry.date} — ${pt.entry.driver_name}`,
        lines: [
          { label: 'Best Lap', value: formatTime(pt.entry.best_time), color: pt.isRecord ? '#B6FF2E' : '#F3F0E8' },
          {
            label: 'Delta',
            value: pt.entry.delta_to_record === 0 ? 'Record!' : formatDelta(pt.entry.delta_to_record),
            color: pt.entry.delta_to_record === 0 ? '#B6FF2E' : '#8A8F98',
          },
          ...(pt.isRecord ? [{ label: 'Status', value: 'New Record', color: '#B6FF2E' }] : []),
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

export default function TrackEvolutionPage() {
  const { id } = useParams<{ id: string }>();
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  const queryPath = (() => {
    const params = new URLSearchParams();
    if (fromDate) params.set('from', fromDate);
    if (toDate) params.set('to', toDate);
    const qs = params.toString();
    return `/tracks/${id}/evolution${qs ? `?${qs}` : ''}`;
  })();

  const { data, isLoading, error } = useQuery({
    queryKey: ['track-evolution', id, fromDate, toDate],
    queryFn: () => api.get<EvolutionResponse>(queryPath),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) return <div className="text-steel font-body">Track not found</div>;

  const evolution = data.evolution ?? [];

  return (
    <div>
      <PageHeader
        title={data.track_name}
        subtitle="Track Evolution"
        actions={
          <div className="flex items-center gap-3">
            <div>
              <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1">
                From
              </label>
              <input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
              />
            </div>
            <div>
              <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1">
                To
              </label>
              <input
                type="date"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                className="bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
                  focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50 transition-colors"
              />
            </div>
          </div>
        }
      />

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Track Record" value={formatTime(data.record_time)} trend="up" />
        <StatCard label="Record Holder" value={data.record_holder ?? '\u2014'} />
        <StatCard label="Sessions Analyzed" value={data.sessions_count} />
        <StatCard
          label="Improvement"
          value={`${data.improvement_pct.toFixed(1)}%`}
          trend={data.improvement_pct > 0 ? 'up' : 'neutral'}
        />
      </div>

      {/* Evolution chart */}
      <div className="mb-6">
        <ChartPanel
          title="Lap Time Evolution"
          subtitle="Best lap per session over time — green dots mark new records"
          loading={isLoading}
          error={error?.message ?? null}
        >
          <EvolutionChart entries={evolution} />
        </ChartPanel>
      </div>

      {/* Data table */}
      {evolution.length > 0 && (
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
                key: 'driver_name',
                header: 'Driver',
                sortable: true,
              },
              {
                key: 'best_time',
                header: 'Best Lap',
                sortable: true,
                className: 'font-telemetry',
                render: (row: EvolutionEntry) => (
                  <span className="text-acid-green">{formatTime(row.best_time)}</span>
                ),
              },
              {
                key: 'delta_to_record',
                header: 'Delta to Record',
                sortable: true,
                className: 'font-telemetry',
                render: (row: EvolutionEntry) => (
                  <span className={row.delta_to_record === 0 ? 'text-acid-green' : 'text-steel'}>
                    {formatDelta(row.delta_to_record)}
                  </span>
                ),
              },
            ]}
            data={evolution}
            keyField="date"
          />
        </div>
      )}
    </div>
  );
}
