'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface ConsistencyData {
  laps: number[];
  sectors: number[];
  deltas: number[][];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 25, right: 15, bottom: 10, left: 40 };

function heatColor(val: number, maxAbs: number): string {
  const t = maxAbs > 0 ? val / maxAbs : 0;
  if (t > 0) {
    return `rgba(255, 42, 42, ${0.2 + Math.min(1, t) * 0.6})`;
  } else {
    return `rgba(182, 255, 46, ${0.2 + Math.min(1, -t) * 0.6})`;
  }
}

function getCell(hover: HoverPoint, w: number, h: number, nSectors: number, nLaps: number) {
  const plotW = w - PAD.left - PAD.right;
  const plotH = h - PAD.top - PAD.bottom;
  const cellW = plotW / nSectors;
  const cellH = plotH / nLaps;
  const col = Math.floor((hover.x - PAD.left) / cellW);
  const row = Math.floor((hover.y - PAD.top) / cellH);
  if (col < 0 || col >= nSectors || row < 0 || row >= nLaps) return null;
  return { row, col, cellW, cellH };
}

export function ConsistencyHeatmap({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'consistency'],
    queryFn: () => api.get<ConsistencyData>(`/sessions/${sessionId}/consistency`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.laps.length === 0) return;

      const { laps, sectors, deltas } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const cellW = plotW / sectors.length;
      const cellH = plotH / laps.length;
      const allVals = deltas.flat();
      const maxAbs = Math.max(...allVals.map(Math.abs), 0.001);

      const hoverCell = hover ? getCell(hover, w, h, sectors.length, laps.length) : null;

      // Header labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      for (let s = 0; s < sectors.length; s++) {
        ctx.fillText(`S${sectors[s]}`, PAD.left + s * cellW + cellW / 2, PAD.top - 8);
      }

      // Rows + cells
      for (let l = 0; l < laps.length; l++) {
        ctx.fillStyle = '#8A8F98';
        ctx.textAlign = 'right';
        ctx.fillText(`L${laps[l]}`, PAD.left - 5, PAD.top + l * cellH + cellH / 2 + 3);

        for (let s = 0; s < sectors.length; s++) {
          const val = deltas[l]?.[s] ?? 0;
          const isHov = hoverCell?.row === l && hoverCell?.col === s;

          ctx.fillStyle = heatColor(val, maxAbs);
          ctx.fillRect(PAD.left + s * cellW + 1, PAD.top + l * cellH + 1, cellW - 2, cellH - 2);

          // Hover highlight border
          if (isHov) {
            ctx.strokeStyle = '#F3F0E8';
            ctx.lineWidth = 2;
            ctx.strokeRect(PAD.left + s * cellW + 1, PAD.top + l * cellH + 1, cellW - 2, cellH - 2);
          }

          if (cellW > 30 && cellH > 14) {
            ctx.fillStyle = '#F3F0E8';
            ctx.font = '8px "IBM Plex Mono", monospace';
            ctx.textAlign = 'center';
            ctx.fillText(
              val > 0 ? `+${val.toFixed(2)}` : val.toFixed(2),
              PAD.left + s * cellW + cellW / 2,
              PAD.top + l * cellH + cellH / 2 + 3,
            );
          }
        }
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.laps.length === 0) return null;
      const { laps, sectors, deltas } = data;
      const col = Math.floor(hover.nx * sectors.length);
      const row = Math.floor(hover.ny * laps.length);
      if (col < 0 || col >= sectors.length || row < 0 || row >= laps.length) return null;
      const val = deltas[row]?.[col] ?? 0;
      return {
        header: `Lap ${laps[row]} — Sector ${sectors[col]}`,
        lines: [
          {
            label: 'Delta',
            value: `${val > 0 ? '+' : ''}${val.toFixed(3)}s`,
            color: val > 0 ? '#FF2A2A' : '#B6FF2E',
          },
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
    <ChartPanel title="Consistency Heatmap" subtitle="Lap-sector time deltas" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
