'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface LapDistData {
  bins: number[];
  counts: number[];
  mean: number;
  median: number;
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 15, right: 15, bottom: 28, left: 40 };

export function LapDistribution({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'lap-distribution'],
    queryFn: () => api.get<LapDistData>(`/sessions/${sessionId}/lap-distribution`),
  });

  const range = useMemo(() => {
    if (!data || data.bins.length === 0) return null;
    const maxCount = Math.max(...data.counts, 1);
    const minBin = data.bins[0];
    const maxBin = data.bins[data.bins.length - 1];
    const binRange = maxBin - minBin || 1;
    return { maxCount, minBin, maxBin, binRange };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !range || data.bins.length === 0) return;

      const { bins, counts, mean, median } = data;
      const { maxCount, minBin, binRange } = range;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const barW = plotW / bins.length;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 3; i++) {
        const y = PAD.top + (i / 3) * plotH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + plotW, y);
        ctx.stroke();
      }

      // Hovered bin index
      const hoveredBin = hover ? Math.floor(hover.nx * bins.length) : -1;

      // Bars
      for (let i = 0; i < bins.length; i++) {
        const barH = (counts[i] / maxCount) * plotH;
        const x = PAD.left + i * barW;
        const y = PAD.top + plotH - barH;

        const isHovered = i === hoveredBin;
        ctx.fillStyle = isHovered ? '#B6FF2ECC' : '#B6FF2E88';
        ctx.fillRect(x + 1, y, barW - 2, barH);

        if (isHovered) {
          ctx.strokeStyle = '#B6FF2E';
          ctx.lineWidth = 1;
          ctx.strokeRect(x + 1, y, barW - 2, barH);
        }
      }

      // Mean line
      if (mean >= minBin && mean <= minBin + binRange) {
        const mx = PAD.left + ((mean - minBin) / binRange) * plotW;
        ctx.save();
        ctx.strokeStyle = '#FFD400';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(mx, PAD.top);
        ctx.lineTo(mx, PAD.top + plotH);
        ctx.stroke();
        ctx.restore();
        ctx.fillStyle = '#FFD400';
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('mean', mx, PAD.top - 3);
      }

      // Median line
      if (median >= minBin && median <= minBin + binRange) {
        const medX = PAD.left + ((median - minBin) / binRange) * plotW;
        ctx.save();
        ctx.strokeStyle = '#FF6A00';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(medX, PAD.top);
        ctx.lineTo(medX, PAD.top + plotH);
        ctx.stroke();
        ctx.restore();
        ctx.fillStyle = '#FF6A00';
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('median', medX, PAD.top + 10);
      }

      // X-axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      const labelStep = Math.max(1, Math.floor(bins.length / 6));
      for (let i = 0; i < bins.length; i += labelStep) {
        const x = PAD.left + (i + 0.5) * barW;
        ctx.fillText(`${bins[i].toFixed(1)}`, x, h - 6);
      }
    },
    [data, range],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.bins.length === 0) return null;
      const idx = Math.floor(hover.nx * data.bins.length);
      if (idx < 0 || idx >= data.bins.length) return null;

      const binCenter = data.bins[idx];
      const m = Math.floor(binCenter / 60);
      const s = (binCenter % 60).toFixed(1);
      return {
        header: `${m}:${s.padStart(4, '0')}`,
        lines: [
          { label: 'Count', value: `${data.counts[idx]} laps`, color: '#B6FF2E' },
        ],
      };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, range],
    padding: PAD,
    getTooltipData,
  });

  if (isLoading)
    return (
      <ChartPanel title="Lap Distribution">
        <div className={`${height} flex items-center justify-center`}>
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </ChartPanel>
    );

  if (!data || data.bins.length === 0)
    return (
      <ChartPanel title="Lap Distribution">
        <div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>
          No data available
        </div>
      </ChartPanel>
    );

  return (
    <ChartPanel title="Lap Distribution" subtitle="Lap time histogram">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
