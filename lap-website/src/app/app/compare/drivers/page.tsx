'use client';

import { useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, ChartPanel } from '@/components/app';
import { useCanvas } from '@/hooks/useCanvas';

/* ---------- types ---------- */

interface DriverOption {
  id: string;
  name: string;
}

interface DriverMetrics {
  id: string;
  name: string;
  sessions: number;
  total_laps: number;
  best_time: number | null;
  avg_score: number | null;
  avg_pace: number | null;
  avg_consistency: number | null;
  avg_execution: number | null;
  avg_robustness: number | null;
}

interface CompareDriversResponse {
  driver_a: DriverMetrics;
  driver_b: DriverMetrics;
}

interface DriverListResponse {
  drivers: DriverOption[];
}

/* ---------- helpers ---------- */

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

/* ---------- component ---------- */

export default function CompareDriversPage() {
  const [driverA, setDriverA] = useState('');
  const [driverB, setDriverB] = useState('');
  const [searchA, setSearchA] = useState('');
  const [searchB, setSearchB] = useState('');

  const { data: driverList } = useQuery({
    queryKey: ['drivers-list'],
    queryFn: () => api.get<DriverListResponse>('/drivers'),
  });

  const drivers = driverList?.drivers ?? [];
  const filteredA = drivers.filter((d) =>
    d.name.toLowerCase().includes(searchA.toLowerCase()),
  );
  const filteredB = drivers.filter((d) =>
    d.name.toLowerCase().includes(searchB.toLowerCase()),
  );

  const canCompare = driverA !== '' && driverB !== '' && driverA !== driverB;

  const { data: comparison, isLoading: comparing } = useQuery({
    queryKey: ['compare-drivers', driverA, driverB],
    queryFn: () =>
      api.get<CompareDriversResponse>(`/compare/drivers?a=${driverA}&b=${driverB}`),
    enabled: canCompare,
  });

  const a = comparison?.driver_a;
  const b = comparison?.driver_b;

  /* ---------- radar chart ---------- */
  const drawRadar = useCallback(
    (ctx: CanvasRenderingContext2D, width: number, height: number) => {
      ctx.fillStyle = '#0B0C0F';
      ctx.fillRect(0, 0, width, height);

      if (!a || !b) return;

      const cx = width / 2;
      const cy = height / 2;
      const radius = Math.min(cx, cy) - 40;

      const labels = ['Pace', 'Consistency', 'Execution', 'Robustness'];
      const valuesA = [a.avg_pace ?? 0, a.avg_consistency ?? 0, a.avg_execution ?? 0, a.avg_robustness ?? 0];
      const valuesB = [b.avg_pace ?? 0, b.avg_consistency ?? 0, b.avg_execution ?? 0, b.avg_robustness ?? 0];
      const maxVal = 25;
      const sides = labels.length;

      // Draw concentric rings
      for (let ring = 1; ring <= 5; ring++) {
        const r = (ring / 5) * radius;
        ctx.beginPath();
        for (let i = 0; i <= sides; i++) {
          const angle = (i / sides) * Math.PI * 2 - Math.PI / 2;
          const x = cx + r * Math.cos(angle);
          const y = cy + r * Math.sin(angle);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = '#8A8F9820';
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Draw axis spokes
      for (let i = 0; i < sides; i++) {
        const angle = (i / sides) * Math.PI * 2 - Math.PI / 2;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle));
        ctx.strokeStyle = '#8A8F9830';
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Draw data polygons
      const drawPolygon = (values: number[], color: string) => {
        ctx.beginPath();
        for (let i = 0; i <= sides; i++) {
          const idx = i % sides;
          const angle = (idx / sides) * Math.PI * 2 - Math.PI / 2;
          const r = (values[idx] / maxVal) * radius;
          const x = cx + r * Math.cos(angle);
          const y = cy + r * Math.sin(angle);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fillStyle = color + '20';
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.stroke();
      };

      drawPolygon(valuesA, '#B6FF2E'); // acid green for A
      drawPolygon(valuesB, '#FF6A00'); // pit orange for B

      // Draw labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      for (let i = 0; i < sides; i++) {
        const angle = (i / sides) * Math.PI * 2 - Math.PI / 2;
        const labelR = radius + 20;
        const x = cx + labelR * Math.cos(angle);
        const y = cy + labelR * Math.sin(angle);
        ctx.fillText(labels[i], x, y + 4);
      }

      // Legend
      ctx.fillStyle = '#B6FF2E';
      ctx.fillRect(16, height - 28, 10, 10);
      ctx.fillStyle = '#F3F0E8';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText(a.name, 32, height - 19);

      ctx.fillStyle = '#FF6A00';
      ctx.fillRect(16, height - 14, 10, 10);
      ctx.fillStyle = '#F3F0E8';
      ctx.fillText(b.name, 32, height - 5);
    },
    [a, b],
  );

  const radarRef = useCanvas(drawRadar, [drawRadar]);

  /* ---------- render ---------- */
  return (
    <div>
      <PageHeader
        title="Compare Drivers"
        subtitle="Head-to-head driver performance analysis"
      />

      {/* Driver selectors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Driver A */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-2">
            Driver A
          </label>
          <input
            type="text"
            placeholder="Search drivers..."
            value={searchA}
            onChange={(e) => setSearchA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
              transition-colors mb-2"
          />
          <select
            value={driverA}
            onChange={(e) => setDriverA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              focus:outline-none focus:border-pit-orange transition-colors"
          >
            <option value="">Select driver...</option>
            {filteredA.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>

        {/* Driver B */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-4">
          <label className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-2">
            Driver B
          </label>
          <input
            type="text"
            placeholder="Search drivers..."
            value={searchB}
            onChange={(e) => setSearchB(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
              transition-colors mb-2"
          />
          <select
            value={driverB}
            onChange={(e) => setDriverB(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              focus:outline-none focus:border-pit-orange transition-colors"
          >
            <option value="">Select driver...</option>
            {filteredB.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Comparison results */}
      {comparing && (
        <div className="flex items-center justify-center h-32">
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      )}

      {a && b && (
        <>
          {/* Driver headers */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="bg-concrete rounded-lg border border-acid-green/30 p-3">
              <p className="font-monument text-sm text-acid-green">{a.name}</p>
              <p className="text-steel font-telemetry text-xs">
                {a.sessions} sessions &middot; {a.total_laps} laps
              </p>
            </div>
            <div className="bg-concrete rounded-lg border border-pit-orange/30 p-3">
              <p className="font-monument text-sm text-pit-orange">{b.name}</p>
              <p className="text-steel font-telemetry text-xs">
                {b.sessions} sessions &middot; {b.total_laps} laps
              </p>
            </div>
          </div>

          {/* Key metrics side by side */}
          <h2 className="font-body text-chalk text-lg mb-3">Performance Summary</h2>
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="space-y-4">
              <StatCard label="Best Time" value={formatTime(a.best_time)} />
              <StatCard label="Avg Score" value={a.avg_score?.toFixed(1) ?? '--'} unit="/100" />
              <StatCard label="Sessions" value={a.sessions} />
              <StatCard label="Total Laps" value={a.total_laps} />
            </div>
            <div className="space-y-4">
              <StatCard label="Best Time" value={formatTime(b.best_time)} />
              <StatCard label="Avg Score" value={b.avg_score?.toFixed(1) ?? '--'} unit="/100" />
              <StatCard label="Sessions" value={b.sessions} />
              <StatCard label="Total Laps" value={b.total_laps} />
            </div>
          </div>

          {/* Radar chart */}
          <ChartPanel
            title="Performance Radar"
            subtitle="Avg scores across four dimensions (green = A, orange = B)"
          >
            <div className="h-72 relative">
              <canvas ref={radarRef} className="absolute inset-0 w-full h-full" />
            </div>
          </ChartPanel>
        </>
      )}

      {!canCompare && !comparing && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <p className="text-steel font-body">
            Select two different drivers above to begin comparison.
          </p>
        </div>
      )}
    </div>
  );
}
