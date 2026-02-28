'use client';

import { useState, useCallback, useMemo, useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { PageHeader, ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

/* ── Types ──────────────────────────────────────────────── */

interface DriverOption {
  driver_id: string;
  driver_name: string;
}

interface DriverMetrics {
  driver_id: string;
  driver_name: string;
  total_sessions: number;
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

/* ── Helpers ────────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

const COLOR_A = '#B6FF2E';
const COLOR_B = '#FF6A00';
const DIMENSIONS = ['Pace', 'Consistency', 'Execution', 'Robustness'] as const;

/* ── Interactive Radar Chart ────────────────────────────── */

const RADAR_PAD = { top: 30, right: 30, bottom: 30, left: 30 };

function RadarChart({ a, b }: { a: DriverMetrics; b: DriverMetrics }) {
  const valuesA = useMemo(() => [a.avg_pace ?? 0, a.avg_consistency ?? 0, a.avg_execution ?? 0, a.avg_robustness ?? 0], [a]);
  const valuesB = useMemo(() => [b.avg_pace ?? 0, b.avg_consistency ?? 0, b.avg_execution ?? 0, b.avg_robustness ?? 0], [b]);
  const maxVal = 25;

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const radius = Math.min(cx - RADAR_PAD.left, cy - RADAR_PAD.top) - 10;
      const sides = DIMENSIONS.length;

      const angleOf = (i: number) => (i / sides) * Math.PI * 2 - Math.PI / 2;

      // Concentric rings
      for (let ring = 1; ring <= 5; ring++) {
        const r = (ring / 5) * radius;
        ctx.beginPath();
        for (let i = 0; i <= sides; i++) {
          const angle = angleOf(i % sides);
          const x = cx + r * Math.cos(angle);
          const y = cy + r * Math.sin(angle);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = 'rgba(138, 143, 152, 0.12)';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Ring label
        if (ring % 2 === 0 || ring === 5) {
          ctx.fillStyle = '#8A8F9860';
          ctx.font = '8px "IBM Plex Mono", monospace';
          ctx.textAlign = 'left';
          ctx.fillText(String((ring / 5) * maxVal), cx + 3, cy - r - 2);
        }
      }

      // Axis spokes
      for (let i = 0; i < sides; i++) {
        const angle = angleOf(i);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle));
        ctx.strokeStyle = 'rgba(138, 143, 152, 0.2)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Hovered dimension
      let hoveredDim = -1;
      if (hover) {
        const mouseAngle = Math.atan2(hover.y - cy, hover.x - cx);
        const normalizedAngle = ((mouseAngle + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2));
        hoveredDim = Math.round((normalizedAngle / (Math.PI * 2)) * sides) % sides;
      }

      // Draw data polygon
      const drawPolygon = (values: number[], color: string, isHovered: boolean) => {
        ctx.beginPath();
        for (let i = 0; i <= sides; i++) {
          const idx = i % sides;
          const angle = angleOf(idx);
          const r = (values[idx] / maxVal) * radius;
          const x = cx + r * Math.cos(angle);
          const y = cy + r * Math.sin(angle);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fillStyle = color + (isHovered ? '30' : '18');
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = isHovered ? 2.5 : 1.5;
        ctx.stroke();

        // Vertex dots
        for (let i = 0; i < sides; i++) {
          const angle = angleOf(i);
          const r = (values[i] / maxVal) * radius;
          const x = cx + r * Math.cos(angle);
          const y = cy + r * Math.sin(angle);
          ctx.beginPath();
          ctx.arc(x, y, i === hoveredDim ? 5 : 3, 0, Math.PI * 2);
          ctx.fillStyle = i === hoveredDim ? color : color + 'CC';
          ctx.fill();
        }
      };

      drawPolygon(valuesA, COLOR_A, true);
      drawPolygon(valuesB, COLOR_B, true);

      // Dimension labels
      ctx.font = '11px "IBM Plex Mono", monospace';
      ctx.textBaseline = 'middle';
      for (let i = 0; i < sides; i++) {
        const angle = angleOf(i);
        const labelR = radius + 22;
        const x = cx + labelR * Math.cos(angle);
        const y = cy + labelR * Math.sin(angle);
        ctx.textAlign = angle > Math.PI / 2 && angle < Math.PI * 1.5 ? 'right' : angle < -Math.PI / 4 || angle > Math.PI / 4 ? 'center' : 'left';
        if (Math.abs(angle + Math.PI / 2) < 0.1) ctx.textAlign = 'center';
        ctx.fillStyle = i === hoveredDim ? '#F3F0E8' : '#8A8F98';
        ctx.font = i === hoveredDim ? 'bold 11px "IBM Plex Mono", monospace' : '11px "IBM Plex Mono", monospace';
        ctx.fillText(DIMENSIONS[i], x, y);
      }

      // Legend
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.fillStyle = COLOR_A;
      ctx.fillRect(16, h - 30, 12, 4);
      ctx.fillStyle = '#F3F0E8';
      ctx.fillText(a.driver_name, 34, h - 25);
      ctx.fillStyle = COLOR_B;
      ctx.fillRect(16, h - 18, 12, 4);
      ctx.fillStyle = '#F3F0E8';
      ctx.fillText(b.driver_name, 34, h - 13);
    },
    [valuesA, valuesB, a.driver_name, b.driver_name],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      // Figure out which dimension is closest
      const w = hover.x / hover.nx; // approximate canvas width
      const h = hover.y / hover.ny;
      const cx = w / 2;
      const cy = h / 2;
      const mouseAngle = Math.atan2(hover.y - cy, hover.x - cx);
      const normalizedAngle = ((mouseAngle + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2));
      const dim = Math.round((normalizedAngle / (Math.PI * 2)) * DIMENSIONS.length) % DIMENSIONS.length;

      const vA = valuesA[dim];
      const vB = valuesB[dim];
      const diff = vB - vA;

      return {
        header: DIMENSIONS[dim],
        lines: [
          { label: 'A', value: `${vA.toFixed(1)}/25`, color: COLOR_A },
          { label: 'B', value: `${vB.toFixed(1)}/25`, color: COLOR_B },
          {
            label: 'Delta',
            value: `${diff > 0 ? '+' : ''}${diff.toFixed(1)}`,
            color: diff > 0 ? COLOR_B : COLOR_A,
          },
        ],
      };
    },
    [valuesA, valuesB],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [valuesA, valuesB],
    padding: RADAR_PAD,
    getTooltipData,
  });

  return (
    <div ref={containerRef} className="relative">
      <canvas ref={canvasRef} className="w-full h-72" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}

/* ── Score Bar ──────────────────────────────────────────── */

function ScoreBar({ label, valA, valB, max }: { label: string; valA: number | null; valB: number | null; max: number }) {
  const pctA = valA != null ? (valA / max) * 100 : 0;
  const pctB = valB != null ? (valB / max) * 100 : 0;
  const diff = valA != null && valB != null ? valB - valA : null;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-steel font-telemetry text-xs uppercase tracking-wider">{label}</span>
        {diff != null && (
          <span className={`font-telemetry text-[10px] ${diff > 0.1 ? 'text-pit-orange' : diff < -0.1 ? 'text-acid-green' : 'text-steel/40'}`}>
            {diff > 0 ? `B +${diff.toFixed(1)}` : diff < 0 ? `A +${Math.abs(diff).toFixed(1)}` : 'Even'}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-acid-green font-telemetry text-[10px] w-8 text-right">{valA?.toFixed(1) ?? '—'}</span>
        <div className="flex-1 h-2 bg-steel/10 rounded-full overflow-hidden">
          <div className="h-full bg-acid-green/70 rounded-full transition-all" style={{ width: `${pctA}%` }} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-pit-orange font-telemetry text-[10px] w-8 text-right">{valB?.toFixed(1) ?? '—'}</span>
        <div className="flex-1 h-2 bg-steel/10 rounded-full overflow-hidden">
          <div className="h-full bg-pit-orange/70 rounded-full transition-all" style={{ width: `${pctB}%` }} />
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ──────────────────────────────────────────── */

export default function CompareDriversPage() {
  const fieldId = useId();
  const [driverA, setDriverA] = useState('');
  const [driverB, setDriverB] = useState('');
  const [searchA, setSearchA] = useState('');
  const [searchB, setSearchB] = useState('');

  const { data: driverList } = useQuery({
    queryKey: ['drivers-list'],
    queryFn: () => api.get<DriverListResponse>('/drivers'),
  });

  const drivers = driverList?.drivers ?? [];

  const filteredA = useMemo(
    () => drivers.filter((d) => d.driver_name.toLowerCase().includes(searchA.toLowerCase())),
    [drivers, searchA],
  );
  const filteredB = useMemo(
    () => drivers.filter((d) => d.driver_name.toLowerCase().includes(searchB.toLowerCase())),
    [drivers, searchB],
  );

  const canCompare = driverA !== '' && driverB !== '' && driverA !== driverB;

  const { data: comparison, isLoading: comparing } = useQuery({
    queryKey: ['compare-drivers', driverA, driverB],
    queryFn: () => api.get<CompareDriversResponse>(`/compare/drivers?a=${driverA}&b=${driverB}`),
    enabled: canCompare,
  });

  const da = comparison?.driver_a;
  const db = comparison?.driver_b;

  return (
    <div>
      <PageHeader
        title="Compare Drivers"
        subtitle="Head-to-head driver performance analysis"
      />

      {/* ── Driver Pickers ─────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="bg-concrete rounded-lg border border-acid-green/20 p-4">
          <label htmlFor={`${fieldId}-search-a`} className="block text-acid-green font-telemetry text-xs uppercase tracking-wider mb-2">
            Driver A
          </label>
          <input
            id={`${fieldId}-search-a`}
            type="text"
            placeholder="Search drivers..."
            value={searchA}
            onChange={(e) => setSearchA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-acid-green focus:ring-1 focus:ring-acid-green/30
              transition-colors mb-2"
          />
          <select
            value={driverA}
            onChange={(e) => setDriverA(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              focus:outline-none focus:border-acid-green transition-colors"
          >
            <option value="">Select driver...</option>
            {filteredA.map((d) => (
              <option key={d.driver_id} value={d.driver_id}>
                {d.driver_name}
              </option>
            ))}
          </select>
        </div>

        <div className="bg-concrete rounded-lg border border-pit-orange/20 p-4">
          <label htmlFor={`${fieldId}-search-b`} className="block text-pit-orange font-telemetry text-xs uppercase tracking-wider mb-2">
            Driver B
          </label>
          <input
            id={`${fieldId}-search-b`}
            type="text"
            placeholder="Search drivers..."
            value={searchB}
            onChange={(e) => setSearchB(e.target.value)}
            className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/30
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
              <option key={d.driver_id} value={d.driver_id}>
                {d.driver_name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Loading ────────────────────────────────────── */}
      {comparing && (
        <div className="flex items-center justify-center h-32">
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      )}

      {/* ── Results ────────────────────────────────────── */}
      {da && db && (
        <>
          {/* Driver header cards */}
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div className="bg-concrete rounded-lg border border-acid-green/30 p-4">
              <span className="font-monument text-sm text-acid-green">A</span>
              <p className="font-monument text-xl text-chalk mt-1">{da.driver_name}</p>
              <div className="flex items-center gap-4 mt-2 text-steel font-telemetry text-xs">
                <span>{da.total_sessions} sessions</span>
                <span>{da.total_laps} laps</span>
                <span>PB: {fmtTime(da.best_time)}</span>
              </div>
            </div>
            <div className="bg-concrete rounded-lg border border-pit-orange/30 p-4">
              <span className="font-monument text-sm text-pit-orange">B</span>
              <p className="font-monument text-xl text-chalk mt-1">{db.driver_name}</p>
              <div className="flex items-center gap-4 mt-2 text-steel font-telemetry text-xs">
                <span>{db.total_sessions} sessions</span>
                <span>{db.total_laps} laps</span>
                <span>PB: {fmtTime(db.best_time)}</span>
              </div>
            </div>
          </div>

          {/* Radar chart */}
          <ChartPanel
            title="Performance Radar"
            subtitle="Avg scores across four scoring dimensions"
          >
            <RadarChart a={da} b={db} />
          </ChartPanel>

          {/* Score breakdown bars */}
          <div className="mt-6">
            <h2 className="font-body text-chalk text-lg mb-4">Score Breakdown</h2>
            <div className="bg-concrete rounded-lg border border-steel/20 p-5 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5">
              <ScoreBar label="Avg Score" valA={da.avg_score} valB={db.avg_score} max={100} />
              <ScoreBar label="Pace" valA={da.avg_pace} valB={db.avg_pace} max={25} />
              <ScoreBar label="Consistency" valA={da.avg_consistency} valB={db.avg_consistency} max={25} />
              <ScoreBar label="Execution" valA={da.avg_execution} valB={db.avg_execution} max={25} />
              <ScoreBar label="Robustness" valA={da.avg_robustness} valB={db.avg_robustness} max={25} />
            </div>
          </div>

          {/* Head-to-head summary */}
          <div className="mt-6 grid grid-cols-3 gap-4">
            <div className="bg-concrete rounded-lg border border-steel/20 p-4 text-center">
              <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-2">Experience</p>
              <div className="flex items-center justify-center gap-6">
                <div>
                  <p className="text-acid-green font-monument text-2xl">{da.total_sessions}</p>
                  <p className="text-steel/40 text-[10px] font-telemetry">sessions</p>
                </div>
                <span className="text-steel/20 text-lg">vs</span>
                <div>
                  <p className="text-pit-orange font-monument text-2xl">{db.total_sessions}</p>
                  <p className="text-steel/40 text-[10px] font-telemetry">sessions</p>
                </div>
              </div>
            </div>
            <div className="bg-concrete rounded-lg border border-steel/20 p-4 text-center">
              <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-2">Total Laps</p>
              <div className="flex items-center justify-center gap-6">
                <div>
                  <p className="text-acid-green font-monument text-2xl">{da.total_laps}</p>
                </div>
                <span className="text-steel/20 text-lg">vs</span>
                <div>
                  <p className="text-pit-orange font-monument text-2xl">{db.total_laps}</p>
                </div>
              </div>
            </div>
            <div className="bg-concrete rounded-lg border border-steel/20 p-4 text-center">
              <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-2">Personal Best</p>
              <div className="flex items-center justify-center gap-4">
                <p className="text-acid-green font-telemetry text-sm">{fmtTime(da.best_time)}</p>
                <span className="text-steel/20 text-sm">vs</span>
                <p className="text-pit-orange font-telemetry text-sm">{fmtTime(db.best_time)}</p>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Prompt state */}
      {!canCompare && !comparing && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <div className="text-4xl mb-3">👥</div>
          <h3 className="font-monument text-lg text-chalk mb-2">Select Two Drivers</h3>
          <p className="text-steel font-body text-sm max-w-md mx-auto">
            Pick two different drivers to see a head-to-head comparison of
            their performance, pace, consistency, and more.
          </p>
        </div>
      )}
    </div>
  );
}
