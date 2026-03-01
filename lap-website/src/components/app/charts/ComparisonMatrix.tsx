'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface ComparisonMatrixData {
  metrics: string[];
  laps: number[];
  values: number[][];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 30, right: 10, bottom: 10, left: 80 };

function cellColor(val: number, min: number, max: number): string {
  const safeVal = Number.isFinite(val) ? val : min;
  const t = (safeVal - min) / (max - min || 1);
  if (t >= 0.7) return 'rgba(182, 255, 46, 0.5)';
  if (t >= 0.4) return 'rgba(255, 212, 0, 0.4)';
  return 'rgba(255, 106, 0, 0.3)';
}

export function ComparisonMatrix({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'comparison-matrix'],
    queryFn: () => api.get<ComparisonMatrixData>(`/sessions/${sessionId}/comparison-matrix`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.metrics.length === 0 || data.laps.length === 0) return;

      const { metrics, laps, values } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const cellW = plotW / Math.max(laps.length, 1);
      const cellH = plotH / Math.max(metrics.length, 1);

      // Compute hovered cell
      let hovRow = -1, hovCol = -1;
      if (hover) {
        hovCol = Math.floor(hover.nx * laps.length);
        hovRow = Math.floor(hover.ny * metrics.length);
        if (hovCol < 0 || hovCol >= laps.length) hovCol = -1;
        if (hovRow < 0 || hovRow >= metrics.length) hovRow = -1;
      }

      // Column headers
      ctx.fillStyle = '#8A8F98';
      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      for (let j = 0; j < laps.length; j++) {
        ctx.fillText(`L${laps[j]}`, PAD.left + j * cellW + cellW / 2, PAD.top - 8);
      }

      // Rows
      for (let m = 0; m < metrics.length; m++) {
        const row = values[m] ?? [];
        const cleanRow = row.filter(Number.isFinite);
        const min = cleanRow.length > 0 ? Math.min(...cleanRow) : 0;
        const max = cleanRow.length > 0 ? Math.max(...cleanRow) : 1;

        // Row label
        ctx.fillStyle = hovRow === m ? '#F3F0E8' : '#8A8F98';
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(metrics[m], PAD.left - 5, PAD.top + m * cellH + cellH / 2);

        for (let j = 0; j < row.length; j++) {
          const x = PAD.left + j * cellW;
          const y = PAD.top + m * cellH;
          const isHov = hovRow === m && hovCol === j;

          ctx.fillStyle = cellColor(row[j], min, max);
          ctx.fillRect(x + 0.5, y + 0.5, cellW - 1, cellH - 1);

          // Hover highlight
          if (isHov) {
            ctx.strokeStyle = '#F3F0E8';
            ctx.lineWidth = 2;
            ctx.strokeRect(x + 0.5, y + 0.5, cellW - 1, cellH - 1);
          }

          if (cellW > 25 && cellH > 12) {
            ctx.fillStyle = '#F3F0E8';
            ctx.font = '7px "IBM Plex Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(row[j].toFixed(1), x + cellW / 2, y + cellH / 2);
          }
        }
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.metrics.length === 0 || data.laps.length === 0) return null;
      const { metrics, laps, values } = data;
      const col = Math.floor(hover.nx * laps.length);
      const row = Math.floor(hover.ny * metrics.length);
      if (col < 0 || col >= laps.length || row < 0 || row >= metrics.length) return null;
      const val = values[row]?.[col];
      if (val == null) return null;
      const rowVals = (values[row] ?? []).filter(Number.isFinite);
      const min = rowVals.length > 0 ? Math.min(...rowVals) : 0;
      const max = rowVals.length > 0 ? Math.max(...rowVals) : 1;
      const pct = ((val - min) / (max - min || 1) * 100).toFixed(0);
      return {
        header: `${metrics[row]} — Lap ${laps[col]}`,
        lines: [
          { label: 'Value', value: val.toFixed(2), color: '#F3F0E8' },
          { label: 'Percentile', value: `${pct}%`, color: Number(pct) >= 70 ? '#B6FF2E' : Number(pct) >= 40 ? '#FFD400' : '#FF6A00' },
        ],
      };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data],
    padding: PAD,
    getTooltipData,
  });

  return (
    <ChartPanel title="Comparison Matrix" subtitle="Multi-metric lap comparison" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
