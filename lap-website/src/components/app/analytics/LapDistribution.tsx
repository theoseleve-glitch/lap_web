/**
 * LapDistribution — histogram of lap times across the session.
 *
 * Native React + TypeScript chart built entirely on the shared chart kit.
 * Shows:
 *   - histogram bars (primary gold) with the best-lap bin in acid-green
 *   - mean and median as dashed vertical reference lines
 *   - hover tooltip: bin range + count + % of session
 *   - legend with mean, median, and standard-deviation inline metadata
 *
 * Owns its ChartCard — render directly, no outer wrapper.
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
  drawReferenceLine,
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

interface LapDistributionProps {
  sessionId: string;
  /** Accepted for backward compatibility; ignored. */
  apiBase?: string;
}

interface Bounds {
  plot: PlotRect;
  xScale: LinearScale;
  yScale: LinearScale;
  nBins: number;
  binWidth: number;
  minT: number;
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

/* ── Component ─────────────────────────────── */

export function LapDistribution({ sessionId }: LapDistributionProps) {
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

  const stats = useMemo(() => {
    const valid = laps.filter(
      (l) => l.is_valid && l.lap_time_s != null && l.lap_time_s > 0,
    );
    if (valid.length < 3) return null;

    const times = valid.map((l) => l.lap_time_s as number);
    const sorted = [...times].sort((a, b) => a - b);
    const minT = sorted[0];
    const maxT = sorted[sorted.length - 1];
    const range = maxT - minT || 1;
    const mean = times.reduce((s, t) => s + t, 0) / times.length;
    const median =
      sorted.length % 2 === 0
        ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
        : sorted[Math.floor(sorted.length / 2)];
    const variance =
      times.reduce((s, t) => s + (t - mean) ** 2, 0) / times.length;
    const stdDev = Math.sqrt(variance);

    // Sturges + sqrt rule for bin count, capped
    const nBins = Math.min(
      Math.max(Math.ceil(Math.sqrt(times.length)), 4),
      15,
    );
    const binWidth = range / nBins;
    const bins: number[] = new Array(nBins).fill(0);
    const binHasBest: boolean[] = new Array(nBins).fill(false);
    const bestIdx = valid.findIndex((l) => l.is_best);

    for (let i = 0; i < times.length; i++) {
      let bi = Math.floor((times[i] - minT) / binWidth);
      if (bi >= nBins) bi = nBins - 1;
      bins[bi]++;
      if (i === bestIdx) binHasBest[bi] = true;
    }

    const maxCount = Math.max(...bins);

    return {
      total: times.length,
      minT,
      maxT,
      mean,
      median,
      stdDev,
      bins,
      binHasBest,
      nBins,
      binWidth,
      maxCount,
    };
  }, [laps]);

  const { containerRef, canvasRef, ready, width, height, dpr } = useChartCanvas({
    minWidth: 40,
    minHeight: 100,
  });

  const [hoverBin, setHoverBin] = useState<number | null>(null);
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
        setHoverBin(null);
        setHoverPos(null);
        return;
      }
      const domainValue = bounds.xScale.fromPixel(px);
      const binIdx = Math.min(
        bounds.nBins - 1,
        Math.max(0, Math.floor((domainValue - bounds.minT) / bounds.binWidth)),
      );
      setHoverBin(binIdx);
      const binCenter =
        bounds.minT + (binIdx + 0.5) * bounds.binWidth;
      setHoverPos({
        x: bounds.xScale.toPixel(binCenter),
        y: bounds.yScale.toPixel(stats.bins[binIdx]),
      });
    };
    const handleLeave = () => {
      setHoverBin(null);
      setHoverPos(null);
    };
    canvas.addEventListener('pointermove', handleMove);
    canvas.addEventListener('pointerleave', handleLeave);
    return () => {
      canvas.removeEventListener('pointermove', handleMove);
      canvas.removeEventListener('pointerleave', handleLeave);
    };
  }, [canvasRef, ready, stats]);

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

    const xScale = createLinearScale(
      [stats.minT, stats.maxT],
      [plot.left, plot.left + plot.width],
    );
    // Y-scale: count on top, 0 at bottom, 15% headroom
    const yScale = createLinearScale(
      [stats.maxCount * 1.15, 0],
      [plot.top, plot.top + plot.height],
    );
    boundsRef.current = {
      plot,
      xScale,
      yScale,
      nBins: stats.nBins,
      binWidth: stats.binWidth,
      minT: stats.minT,
    };

    // ── Grid ──
    const yTicks = niceTicks(0, stats.maxCount, 4).filter((t) => t > 0);
    drawGrid(ctx, {
      plot,
      y: { scale: yScale, ticks: yTicks },
    });

    // ── Bars ──
    const binPixelWidth = plot.width / stats.nBins;
    const barWidth = Math.max(2, binPixelWidth - 2);

    for (let i = 0; i < stats.nBins; i++) {
      const count = stats.bins[i];
      if (count === 0) continue;
      const binStart = stats.minT + i * stats.binWidth;
      const centerX = xScale.toPixel(binStart + stats.binWidth / 2);
      const x = centerX - barWidth / 2;
      const y = yScale.toPixel(count);
      const barH = yScale.toPixel(0) - y;

      const color = stats.binHasBest[i]
        ? chartColor.series.positive
        : chartColor.series.primary;
      const isHover = hoverBin === i;

      ctx.save();
      ctx.fillStyle = color;
      ctx.globalAlpha = isHover ? 0.95 : 0.7;
      ctx.beginPath();
      ctx.roundRect(x, y, barWidth, barH, 2);
      ctx.fill();
      ctx.restore();

      // Count label above each bar (only if bar is tall enough)
      if (barH > 16) {
        ctx.save();
        ctx.fillStyle = chartColor.text;
        ctx.globalAlpha = isHover ? 1 : 0.8;
        ctx.font = '10px "Space Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(String(count), centerX, y - 3);
        ctx.restore();
      }
    }

    // ── Reference lines (mean, median) ──
    drawReferenceLine(ctx, {
      orientation: 'vertical',
      plot,
      scale: xScale,
      value: stats.mean,
      color: chartColor.palette[4],
      dashed: true,
    });
    drawReferenceLine(ctx, {
      orientation: 'vertical',
      plot,
      scale: xScale,
      value: stats.median,
      color: chartColor.series.warning,
      dashed: true,
    });

    // ── Axes ──
    drawAxis(ctx, {
      orientation: 'y',
      plot,
      scale: yScale,
      ticks: yTicks,
      format: (v) => String(Math.round(v)),
    });
    drawAxis(ctx, {
      orientation: 'x',
      plot,
      scale: xScale,
      tickCount: 6,
      format: (v) => formatTime(v),
    });
  }, [canvasRef, ready, stats, width, height, dpr, hoverBin]);

  const isEmpty = !loading && !error && (!stats || stats.total < 3);

  return (
    <ChartCard>
      <ChartHeader
        title="Lap Distribution"
        subtitle={stats ? `${stats.total} laps` : undefined}
        info="Histogram of lap times. Dashed lines mark mean and median. Tighter distribution = more consistent pace."
      />
      <ChartBody
        layout="fixed"
        height={260}
        aria-label="Histogram of lap times across the session"
      >
        <div ref={containerRef} className="relative w-full h-full">
          <canvas ref={canvasRef} />
          {loading && <ChartLoadingState />}
          {!loading && error && <ChartErrorState message={error} />}
          {isEmpty && (
            <ChartEmptyState
              message="Not enough laps"
              hint="Need at least 3 valid laps for a distribution."
            />
          )}
          {stats && hoverBin != null && hoverPos && stats.bins[hoverBin] > 0 && (
            <ChartTooltip
              x={hoverPos.x}
              y={hoverPos.y}
              containerWidth={width}
              title={`${formatTime(
                stats.minT + hoverBin * stats.binWidth,
              )} – ${formatTime(
                stats.minT + (hoverBin + 1) * stats.binWidth,
              )}`}
              rows={[
                {
                  label: 'Laps',
                  value: String(stats.bins[hoverBin]),
                  color: stats.binHasBest[hoverBin]
                    ? chartColor.series.positive
                    : chartColor.series.primary,
                },
                {
                  label: 'Share',
                  value: `${((stats.bins[hoverBin] / stats.total) * 100).toFixed(0)}%`,
                },
                ...(stats.binHasBest[hoverBin]
                  ? [
                      {
                        label: '★ Contains best',
                        value: '',
                        color: chartColor.series.positive,
                      },
                    ]
                  : []),
              ]}
            />
          )}
        </div>
      </ChartBody>
      <ChartLegend
        items={
          stats
            ? [
                {
                  label: 'Lap bin',
                  color: chartColor.series.primary,
                  symbol: 'bar',
                },
                {
                  label: 'Best lap bin',
                  color: chartColor.series.positive,
                  symbol: 'bar',
                },
                {
                  label: 'Mean',
                  color: chartColor.palette[4],
                  symbol: 'dashed',
                  meta: formatTime(stats.mean),
                },
                {
                  label: 'Median',
                  color: chartColor.series.warning,
                  symbol: 'dashed',
                  meta: formatTime(stats.median),
                },
                {
                  label: 'σ',
                  color: chartColor.series.neutral,
                  symbol: 'line',
                  meta: `${stats.stdDev.toFixed(3)}s`,
                },
              ]
            : []
        }
      />
    </ChartCard>
  );
}
