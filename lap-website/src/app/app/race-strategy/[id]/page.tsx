'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { useRef, useEffect } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel } from '@/components/app';

interface Stint {
  stint_number: number;
  compound: string;
  start_lap: number;
  end_lap: number;
  laps: number;
  avg_time: number;
}

interface StrategyDetail {
  id: number;
  name: string;
  track_name: string;
  race_laps: number;
  base_lap_time: number;
  pit_stops: number;
  total_time: number;
  optimal_time: number;
  time_penalty: number;
  stints: Stint[];
  lap_times: number[];
  status: string;
}

const compoundColors: Record<string, string> = {
  soft: '#FF2A2A',
  medium: '#FFD400',
  hard: '#F3F0E8',
  wet: '#3B82F6',
  inter: '#22C55E',
};

function drawStrategyChart(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  data: StrategyDetail,
) {
  ctx.clearRect(0, 0, w, h);
  const pad = { top: 20, right: 20, bottom: 30, left: 50 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  if (data.lap_times.length === 0) return;

  const minT = Math.min(...data.lap_times) * 0.98;
  const maxT = Math.max(...data.lap_times) * 1.02;
  const scaleX = cw / (data.lap_times.length - 1 || 1);
  const scaleY = ch / (maxT - minT || 1);

  // Grid
  ctx.strokeStyle = 'rgba(138,143,152,0.15)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i < 5; i++) {
    const y = pad.top + (ch * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + cw, y);
    ctx.stroke();
  }

  // Stint backgrounds
  for (const stint of data.stints) {
    const x1 = pad.left + (stint.start_lap - 1) * scaleX;
    const x2 = pad.left + (stint.end_lap - 1) * scaleX;
    ctx.fillStyle = (compoundColors[stint.compound] ?? '#8A8F98') + '15';
    ctx.fillRect(x1, pad.top, x2 - x1, ch);
  }

  // Lap time line
  ctx.strokeStyle = '#B6FF2E';
  ctx.lineWidth = 2;
  ctx.beginPath();
  data.lap_times.forEach((t, i) => {
    const x = pad.left + i * scaleX;
    const y = pad.top + (maxT - t) * scaleY;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Dots
  data.lap_times.forEach((t, i) => {
    const stint = data.stints.find((s) => i + 1 >= s.start_lap && i + 1 <= s.end_lap);
    const color = stint ? (compoundColors[stint.compound] ?? '#8A8F98') : '#B6FF2E';
    const x = pad.left + i * scaleX;
    const y = pad.top + (maxT - t) * scaleY;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });

  // X-axis label
  ctx.fillStyle = '#8A8F98';
  ctx.font = '10px "IBM Plex Mono"';
  ctx.textAlign = 'center';
  ctx.fillText('Lap', pad.left + cw / 2, h - 4);

  // Y-axis label
  ctx.save();
  ctx.translate(12, pad.top + ch / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Lap Time (s)', 0, 0);
  ctx.restore();
}

function formatTime(s: number): string {
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${secs.toFixed(1).padStart(4, '0')}`;
}

export default function RaceStrategyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const { data: strategy, isLoading } = useQuery({
    queryKey: ['race-strategy', id],
    queryFn: () => api.get<StrategyDetail>(`/race-strategy/${id}`),
  });

  useEffect(() => {
    if (!strategy || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    drawStrategyChart(ctx, rect.width, rect.height, strategy);
  }, [strategy]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!strategy) return <div className="text-steel font-body">Strategy not found</div>;

  return (
    <div>
      <PageHeader
        title={strategy.name}
        subtitle={`${strategy.track_name} · ${strategy.race_laps} laps · ${strategy.pit_stops} stops`}
        actions={
          <Link
            href={`/app/race-strategy/${id}/live`}
            className="px-4 py-2 bg-acid-green text-asphalt font-telemetry text-sm rounded hover:bg-acid-green/80 transition-colors"
          >
            Go Live
          </Link>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Time" value={formatTime(strategy.total_time)} />
        <StatCard label="Optimal" value={formatTime(strategy.optimal_time)} trend="up" />
        <StatCard
          label="Penalty"
          value={`+${strategy.time_penalty.toFixed(1)}s`}
          trend={strategy.time_penalty > 5 ? 'down' : 'neutral'}
        />
        <StatCard label="Pit Stops" value={strategy.pit_stops} />
      </div>

      {/* Strategy chart */}
      <ChartPanel title="Lap Time Projection" subtitle="Projected lap times by stint and compound">
        <canvas ref={canvasRef} className="w-full h-64" />
      </ChartPanel>

      {/* Stints table */}
      <div className="mt-6 bg-concrete rounded-lg border border-steel/20 overflow-hidden">
        <div className="px-4 py-3 border-b border-steel/20">
          <h3 className="font-body text-chalk text-sm">Stint Plan</h3>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b border-steel/20">
              <th className="text-left px-4 py-2 text-steel font-telemetry text-xs uppercase">
                Stint
              </th>
              <th className="text-left px-4 py-2 text-steel font-telemetry text-xs uppercase">
                Compound
              </th>
              <th className="text-left px-4 py-2 text-steel font-telemetry text-xs uppercase">
                Laps
              </th>
              <th className="text-left px-4 py-2 text-steel font-telemetry text-xs uppercase">
                Range
              </th>
              <th className="text-left px-4 py-2 text-steel font-telemetry text-xs uppercase">
                Avg Time
              </th>
            </tr>
          </thead>
          <tbody>
            {strategy.stints.map((s) => (
              <tr key={s.stint_number} className="border-b border-steel/10">
                <td className="px-4 py-2 font-telemetry text-chalk">{s.stint_number}</td>
                <td className="px-4 py-2">
                  <span
                    className="font-telemetry text-sm uppercase"
                    style={{ color: compoundColors[s.compound] ?? '#8A8F98' }}
                  >
                    {s.compound}
                  </span>
                </td>
                <td className="px-4 py-2 font-telemetry text-chalk">{s.laps}</td>
                <td className="px-4 py-2 font-telemetry text-steel text-sm">
                  L{s.start_lap}–L{s.end_lap}
                </td>
                <td className="px-4 py-2 font-telemetry text-acid-green">
                  {s.avg_time.toFixed(3)}s
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex gap-3">
        <Link
          href={`/app/race-strategy/${id}/live`}
          className="px-4 py-2 bg-acid-green text-asphalt font-telemetry text-sm rounded hover:bg-acid-green/80 transition-colors"
        >
          Start Live Session
        </Link>
        <Link
          href={`/app/race-strategy/${id}/summary`}
          className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk transition-colors"
        >
          View Summary
        </Link>
      </div>
    </div>
  );
}
