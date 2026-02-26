'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useRef, useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel, DataTable } from '@/components/app';

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
/*  Canvas draw                                                        */
/* ------------------------------------------------------------------ */

const STEEL = 'rgba(138,143,152,1)';
const STEEL_20 = 'rgba(138,143,152,0.2)';
const ACID_GREEN = '#B6FF2E';

function drawEvolutionChart(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  entries: EvolutionEntry[],
) {
  ctx.clearRect(0, 0, w, h);

  if (entries.length === 0) {
    ctx.fillStyle = STEEL;
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('No evolution data', w / 2, h / 2);
    return;
  }

  /* Padding */
  const padL = 64;
  const padR = 20;
  const padT = 16;
  const padB = 48;
  const chartW = w - padL - padR;
  const chartH = h - padT - padB;

  /* Data ranges */
  const times = entries.map((e) => e.best_time);
  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const rangeT = maxT - minT || 1;

  const dates = entries.map((e) => new Date(e.date).getTime());
  const minDate = Math.min(...dates);
  const maxDate = Math.max(...dates);
  const rangeDate = maxDate - minDate || 1;

  const xOf = (d: number) => padL + ((d - minDate) / rangeDate) * chartW;
  const yOf = (t: number) => padT + ((t - minT) / rangeT) * chartH;

  /* Grid lines (horizontal) */
  const gridRows = 5;
  ctx.strokeStyle = STEEL_20;
  ctx.lineWidth = 1;
  for (let i = 0; i <= gridRows; i++) {
    const y = padT + (i / gridRows) * chartH;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + chartW, y);
    ctx.stroke();

    /* Y-axis labels */
    const val = minT + (i / gridRows) * rangeT;
    ctx.fillStyle = STEEL;
    ctx.font = '11px "IBM Plex Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.fillText(formatTime(val), padL - 8, y);
  }

  /* X-axis labels */
  const uniqueDates = Array.from(new Set(entries.map((e) => e.date))).sort();
  const maxXLabels = Math.min(uniqueDates.length, 8);
  const step = Math.max(1, Math.floor(uniqueDates.length / maxXLabels));
  ctx.font = '11px "IBM Plex Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillStyle = STEEL;
  for (let i = 0; i < uniqueDates.length; i += step) {
    const d = new Date(uniqueDates[i]).getTime();
    const x = xOf(d);
    ctx.fillText(uniqueDates[i], x, padT + chartH + 8);
  }

  /* Compute record progression: for each entry in chronological order,
     track the running minimum. Mark entries where the record improved. */
  const sorted = [...entries].sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
  );
  let runningMin = Infinity;
  const recordPoints: { x: number; y: number }[] = [];
  const isRecord: boolean[] = [];

  for (const entry of sorted) {
    if (entry.best_time < runningMin) {
      runningMin = entry.best_time;
      isRecord.push(true);
      recordPoints.push({
        x: xOf(new Date(entry.date).getTime()),
        y: yOf(entry.best_time),
      });
    } else {
      isRecord.push(false);
    }
  }

  /* Non-record data points (steel dots) */
  sorted.forEach((entry, i) => {
    if (isRecord[i]) return;
    const x = xOf(new Date(entry.date).getTime());
    const y = yOf(entry.best_time);
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fillStyle = STEEL;
    ctx.fill();
  });

  /* Record progression line */
  if (recordPoints.length > 1) {
    ctx.beginPath();
    ctx.moveTo(recordPoints[0].x, recordPoints[0].y);
    for (let i = 1; i < recordPoints.length; i++) {
      ctx.lineTo(recordPoints[i].x, recordPoints[i].y);
    }
    ctx.strokeStyle = ACID_GREEN;
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  /* Record data points (acid-green dots) */
  for (const pt of recordPoints) {
    ctx.beginPath();
    ctx.arc(pt.x, pt.y, 6, 0, Math.PI * 2);
    ctx.fillStyle = ACID_GREEN;
    ctx.fill();
  }
}

/* ------------------------------------------------------------------ */
/*  Page component                                                     */
/* ------------------------------------------------------------------ */

export default function TrackEvolutionPage() {
  const { id } = useParams<{ id: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
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
    drawEvolutionChart(ctx, rect.width, rect.height, data.evolution);
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
        <StatCard
          label="Track Record"
          value={formatTime(data.record_time)}
          trend="up"
        />
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
          subtitle="Best lap per session over time"
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
