'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface ThrottleMapData {
  distances: number[];
  laps: number[];
  throttle: number[][];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 25, right: 15, bottom: 10, left: 40 };

function throttleColor(pct: number): string {
  if (pct >= 0.8) return '#B6FF2E';
  if (pct >= 0.5) return '#FFD400';
  if (pct >= 0.2) return '#FF6A00';
  return '#FF2A2A';
}

export function ThrottleHeatmap({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'throttle-map'],
    queryFn: () => api.get<ThrottleMapData>(`/sessions/${sessionId}/throttle-map`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.distances.length === 0 || data.laps.length === 0) return;

      const { distances, laps, throttle } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const cellW = plotW / distances.length;
      const cellH = plotH / laps.length;

      // Compute hovered cell
      let hovRow = -1, hovCol = -1;
      if (hover) {
        hovCol = Math.floor(hover.nx * distances.length);
        hovRow = Math.floor(hover.ny * laps.length);
        if (hovCol < 0 || hovCol >= distances.length) hovCol = -1;
        if (hovRow < 0 || hovRow >= laps.length) hovRow = -1;
      }

      // Column headers (sample distances)
      ctx.fillStyle = '#8A8F98';
      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      const step = Math.max(1, Math.floor(distances.length / 8));
      for (let d = 0; d < distances.length; d += step) {
        ctx.fillText(`${distances[d].toFixed(0)}m`, PAD.left + d * cellW + cellW / 2, PAD.top - 8);
      }

      // Rows
      for (let l = 0; l < laps.length; l++) {
        ctx.fillStyle = '#8A8F98';
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`L${laps[l]}`, PAD.left - 5, PAD.top + l * cellH + cellH / 2 + 3);

        for (let d = 0; d < distances.length; d++) {
          const val = throttle[l]?.[d] ?? 0;
          ctx.fillStyle = throttleColor(val);
          ctx.globalAlpha = 0.3 + val * 0.7;
          ctx.fillRect(PAD.left + d * cellW, PAD.top + l * cellH, cellW + 0.5, cellH);
        }
        ctx.globalAlpha = 1;
      }

      // Hover highlight
      if (hovRow >= 0 && hovCol >= 0) {
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 2;
        ctx.strokeRect(
          PAD.left + hovCol * cellW,
          PAD.top + hovRow * cellH,
          cellW + 0.5,
          cellH,
        );
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.distances.length === 0 || data.laps.length === 0) return null;
      const { distances, laps, throttle } = data;
      const col = Math.floor(hover.nx * distances.length);
      const row = Math.floor(hover.ny * laps.length);
      if (col < 0 || col >= distances.length || row < 0 || row >= laps.length) return null;
      const val = throttle[row]?.[col] ?? 0;
      return {
        header: `Lap ${laps[row]} — ${distances[col].toFixed(0)}m`,
        lines: [
          { label: 'Throttle', value: `${(val * 100).toFixed(0)}%`, color: throttleColor(val) },
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
    <ChartPanel title="Throttle Heatmap" subtitle="Throttle application per lap/distance" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
