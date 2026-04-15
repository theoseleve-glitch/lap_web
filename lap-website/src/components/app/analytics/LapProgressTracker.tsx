/**
 * LapProgressTracker — lap time progression over a session.
 *
 * Native React + TypeScript chart built entirely on the shared chart kit.
 * Shows:
 *   - per-lap time as a solid gold line with dots
 *   - running personal best as a dashed marshal-yellow line
 *   - session mean as a dashed neutral line (with pace zones above/below)
 *   - best lap highlighted with an acid-green ring
 *   - hover tooltip: time, delta vs best, delta vs mean
 *
 * This component OWNS its ChartCard — parents should render it directly
 * without wrapping it in their own container.
 */

'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api-client';
import {
  ChartCard,
  ChartHeader,
  ChartBody,
  ChartLegend,
  ChartTooltip,
  ChartLoadingState,
  ChartErrorState,
  ChartEmptyState,
  chartColor,
  plotPadding,
  createLinearScale,
  niceTicks,
  drawAxis,
  drawGrid,
  drawCrosshair,
  useChartCanvas,
  type LinearScale,
  type PlotRect,
} from '@/components/shared/chart-kit';

/* ── Types ─────────────────────────────────── */

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  is_best: number;
  is_valid: number;
}

interface LapProgressTrackerProps {
  sessionId: string;
  /** Accepted for backward compatibility; ignored — uses global api client. */
  apiBase?: string;
}

interface Bounds {
  plot: PlotRect;
  xScale: LinearScale;
  yScale: LinearScale;
}

/* ── Helpers ───────────────────────────────── */

function formatTime(s: number): string {
  if (!Number.isFinite(s)) return '—';
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const sec = s - m * 60;
    return `${m}:${sec.toFixed(2).padStart(5, '0')}`;
  }
  return `${s.toFixed(2)}s`;
}

function formatDelta(v: number): string {
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  return `${sign}${Math.abs(v).toFixed(3)}s`;
}

/**
 * Pick ~`target` evenly-spaced x-axis tick indices, always including the last.
 * Integer indices only — these are used to look up lap numbers.
 */
function buildXTickIndices(n: number, target: number): number[] {
  if (n <= target) return Array.from({ length: n }, (_, i) => i);
  const step = Math.max(1, Math.floor((n - 1) / (target - 1)));
  const ticks: number[] = [];
  for (let i = 0; i < n; i += step) ticks.push(i);
  if (ticks[ticks.length - 1] !== n - 1) ticks.push(n - 1);
  return ticks;
}

/* ── Component ─────────────────────────────── */

export function LapProgressTracker({ sessionId }: LapProgressTrackerProps) {
  // ── Data fetch ──────────────────────────────────────────────
  const [laps, setLaps] = useState<LapData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res = await api.get<{ laps: LapData[] }>(
          `/sessions/${sessionId}/laps`,
        );
        if (!cancelled) setLaps(res.laps ?? []);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load laps');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // ── Derive statistics ───────────────────────────────────────
  const stats = useMemo(() => {
    const valid = laps.filter(
      (l) => l.is_valid && l.lap_time_s != null && l.lap_time_s > 0,
    );
    if (valid.length < 2) {
      return null;
    }
    const times = valid.map((l) => l.lap_time_s as number);
    const lapNums = valid.map((l) => l.lap_number);
    const mean = times.reduce((s, t) => s + t, 0) / times.length;

    const runningPB: number[] = [];
    let pb = Infinity;
    for (const t of times) {
      if (t < pb) pb = t;
      runningPB.push(pb);
    }

    const best = Math.min(...times);
    const bestLapIdx = valid.findIndex((l) => l.is_best);
    const minT = Math.min(...times) * 0.995;
    const maxT = Math.max(...times) * 1.005;

    return {
      valid,
      times,
      lapNums,
      mean,
      best,
      bestLapIdx,
      runningPB,
      minT,
      maxT,
    };
  }, [laps]);

  // ── Canvas + resize ─────────────────────────────────────────
  const { containerRef, canvasRef, ready, width, height, dpr } = useChartCanvas({
    minWidth: 40,
    minHeight: 100,
  });

  // ── Local hover (not distance-synced — this is a session-level chart) ──
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null);
  const boundsRef = useRef<Bounds | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !ready || !stats) return;

    const handleMove = (e: PointerEvent) => {
      const bounds = boundsRef.current;
      if (!bounds) return;
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const inside =
        px >= bounds.plot.left &&
        px <= bounds.plot.left + bounds.plot.width &&
        py >= bounds.plot.top &&
        py <= bounds.plot.top + bounds.plot.height;
      if (!inside) {
        setHoverIdx(null);
        setHoverPos(null);
        return;
      }
      const idxFloat = bounds.xScale.fromPixel(px);
      const idx = Math.max(
        0,
        Math.min(stats.valid.length - 1, Math.round(idxFloat)),
      );
      setHoverIdx(idx);
      setHoverPos({
        x: bounds.xScale.toPixel(idx),
        y: bounds.yScale.toPixel(stats.times[idx]),
      });
    };
    const handleLeave = () => {
      setHoverIdx(null);
      setHoverPos(null);
    };

    canvas.addEventListener('pointermove', handleMove);
    canvas.addEventListener('pointerleave', handleLeave);
    return () => {
      canvas.removeEventListener('pointermove', handleMove);
      canvas.removeEventListener('pointerleave', handleLeave);
    };
  }, [canvasRef, ready, stats]);

  // ── Draw ─────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !ready || !stats) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const pad = plotPadding.comfortable;
    const plot: PlotRect = {
      left: pad.left,
      top: pad.top,
      width: width - pad.left - pad.right,
      height: height - pad.top - pad.bottom,
    };

    // Y-scale is inverted: lower lap time = higher on chart (less y-pixel)
    const xScale = createLinearScale(
      [0, stats.valid.length - 1],
      [plot.left, plot.left + plot.width],
    );
    const yScale = createLinearScale(
      [stats.maxT, stats.minT],
      [plot.top, plot.top + plot.height],
    );
    boundsRef.current = { plot, xScale, yScale };

    const yTicks = niceTicks(stats.minT, stats.maxT, 5);
    const xTickIndices = buildXTickIndices(stats.valid.length, 8);

    // ── Grid ───────────────────────────────────────
    drawGrid(ctx, {
      plot,
      y: { scale: yScale, ticks: yTicks },
    });

    // ── Pace zones (faster above the mean line, slower below) ──
    const meanY = yScale.toPixel(stats.mean);
    ctx.fillStyle = `${chartColor.series.positive}14`; // 8% alpha
    ctx.fillRect(plot.left, plot.top, plot.width, Math.max(0, meanY - plot.top));
    ctx.fillStyle = `${chartColor.series.negative}0F`; // 6% alpha
    ctx.fillRect(
      plot.left,
      meanY,
      plot.width,
      Math.max(0, plot.top + plot.height - meanY),
    );

    // ── Mean line (dashed neutral) ─────────────────
    ctx.save();
    ctx.strokeStyle = chartColor.series.neutral;
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 3]);
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    ctx.moveTo(plot.left, meanY);
    ctx.lineTo(plot.left + plot.width, meanY);
    ctx.stroke();
    ctx.restore();

    // ── Running PB (dashed marshal-yellow) ─────────
    ctx.save();
    ctx.strokeStyle = chartColor.series.warning;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    for (let i = 0; i < stats.valid.length; i++) {
      const x = xScale.toPixel(i);
      const y = yScale.toPixel(stats.runningPB[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();

    // ── Lap time line (solid gold) ─────────────────
    ctx.strokeStyle = chartColor.series.primary;
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < stats.valid.length; i++) {
      const x = xScale.toPixel(i);
      const y = yScale.toPixel(stats.times[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // ── Dots (best lap has an acid-green ring) ────
    for (let i = 0; i < stats.valid.length; i++) {
      const x = xScale.toPixel(i);
      const y = yScale.toPixel(stats.times[i]);
      const isBest = !!stats.valid[i].is_best;
      const isHover = hoverIdx === i;

      ctx.beginPath();
      ctx.arc(x, y, isBest ? 4 : isHover ? 4 : 2.5, 0, Math.PI * 2);
      ctx.fillStyle = chartColor.series.primary;
      ctx.fill();

      if (isBest) {
        ctx.strokeStyle = chartColor.series.positive;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.stroke();
      } else if (isHover) {
        ctx.strokeStyle = chartColor.text;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    // ── Hover crosshair ────────────────────────────
    if (hoverIdx != null) {
      drawCrosshair(ctx, { plot, x: xScale.toPixel(hoverIdx) });
    }

    // ── Axes (kit primitives) ──────────────────────
    drawAxis(ctx, {
      orientation: 'y',
      plot,
      scale: yScale,
      ticks: yTicks,
      format: (v) => formatTime(v),
    });
    drawAxis(ctx, {
      orientation: 'x',
      plot,
      scale: xScale,
      ticks: xTickIndices,
      format: (i) => {
        const idx = Math.round(i);
        return stats.lapNums[idx] != null ? `L${stats.lapNums[idx]}` : '';
      },
    });
  }, [
    canvasRef,
    ready,
    stats,
    width,
    height,
    dpr,
    hoverIdx,
  ]);

  // ── Render ──────────────────────────────────────
  const isEmpty = !loading && !error && (!stats || stats.valid.length < 2);

  return (
    <ChartCard>
      <ChartHeader
        title="Lap Progress"
        subtitle={stats ? `${stats.valid.length} valid laps` : undefined}
      />
      <ChartBody
        layout="fixed"
        height={260}
        aria-label="Lap time progress chart showing improvement across the session"
      >
        <div ref={containerRef} className="relative w-full h-full">
          <canvas ref={canvasRef} />
          {loading && <ChartLoadingState />}
          {!loading && error && <ChartErrorState message={error} />}
          {isEmpty && (
            <ChartEmptyState
              message="Not enough valid laps"
              hint="Need at least 2 valid laps to show progression."
            />
          )}
          {stats && hoverIdx != null && hoverPos && (
            <ChartTooltip
              x={hoverPos.x}
              y={hoverPos.y}
              containerWidth={width}
              title={`Lap ${stats.lapNums[hoverIdx]}`}
              rows={[
                {
                  label: 'Time',
                  value: formatTime(stats.times[hoverIdx]),
                  color: chartColor.series.primary,
                },
                {
                  label: 'vs Best',
                  value:
                    hoverIdx === stats.bestLapIdx
                      ? 'session best'
                      : formatDelta(stats.times[hoverIdx] - stats.best),
                  color:
                    hoverIdx === stats.bestLapIdx
                      ? chartColor.series.positive
                      : undefined,
                },
                {
                  label: 'vs Mean',
                  value: formatDelta(stats.times[hoverIdx] - stats.mean),
                },
              ]}
            />
          )}
        </div>
      </ChartBody>
      <ChartLegend
        items={[
          { label: 'Lap time', color: chartColor.series.primary, symbol: 'line' },
          {
            label: 'Running PB',
            color: chartColor.series.warning,
            symbol: 'dashed',
          },
          {
            label: `Mean${stats ? ` ${formatTime(stats.mean)}` : ''}`,
            color: chartColor.series.neutral,
            symbol: 'dashed',
          },
          {
            label: 'Best lap',
            color: chartColor.series.positive,
            symbol: 'hollow',
          },
        ]}
      />
    </ChartCard>
  );
}
