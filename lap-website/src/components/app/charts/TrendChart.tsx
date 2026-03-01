'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface TrendData {
  distances: number[];
  pace_delta: number[];
  consistency_index: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 15, right: 40, bottom: 30, left: 45 };

export function TrendChart({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'trends'],
    queryFn: () => api.get<TrendData>(`/sessions/${sessionId}/trends`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.distances.length === 0) return;

      const { distances, pace_delta, consistency_index } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const minDist = distances[0], maxDist = distances[distances.length - 1];
      const dR = maxDist - minDist || 1;
      const cleanPace = pace_delta.filter(Number.isFinite).map(Math.abs);
      const cleanConsist = consistency_index.filter(Number.isFinite);
      const maxPace = cleanPace.length > 0 ? Math.max(...cleanPace, 0.1) : 0.1;
      const maxConsist = cleanConsist.length > 0 ? Math.max(...cleanConsist, 0.01) : 0.01;
      const cy = PAD.top + plotH / 2;

      const toX = (d: number) => { const v = PAD.left + ((d - minDist) / dR) * plotW; return Number.isFinite(v) ? v : PAD.left; };

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + plotW, y);
        ctx.stroke();
      }

      const safePaceY = (v: number) => {
        const safe = Number.isFinite(v) ? v : 0;
        const y = cy - (safe / maxPace) * (plotH / 2);
        return Number.isFinite(y) ? y : cy;
      };
      const safeConsistY = (v: number) => {
        const safe = Number.isFinite(v) ? v : 0;
        const y = PAD.top + plotH - (safe / maxConsist) * plotH;
        return Number.isFinite(y) ? y : PAD.top;
      };

      // Pace delta line (centered on zero)
      ctx.beginPath();
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 1.5;
      for (let i = 0; i < distances.length; i++) {
        const x = toX(distances[i]);
        const y = safePaceY(pace_delta[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Consistency index line
      ctx.beginPath();
      ctx.strokeStyle = '#FFD400';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      for (let i = 0; i < distances.length; i++) {
        const x = toX(distances[i]);
        const y = safeConsistY(consistency_index[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Zero line
      ctx.beginPath();
      ctx.strokeStyle = '#8A8F98';
      ctx.lineWidth = 0.5;
      ctx.moveTo(PAD.left, cy);
      ctx.lineTo(PAD.left + plotW, cy);
      ctx.stroke();

      // Hover dots
      if (hover) {
        const hoverDist = minDist + hover.nx * dR;
        let idx = 0, diff = Infinity;
        for (let i = 0; i < distances.length; i++) {
          const d = Math.abs(distances[i] - hoverDist);
          if (d < diff) { diff = d; idx = i; }
        }
        const x = toX(distances[idx]);
        // Pace dot
        ctx.beginPath();
        ctx.arc(x, safePaceY(pace_delta[idx]), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        // Consistency dot
        ctx.beginPath();
        ctx.arc(x, safeConsistY(consistency_index[idx]), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#FFD400';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#B6FF2E';
      ctx.fillRect(PAD.left + 5, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Pace delta', PAD.left + 20, PAD.top + 6);
      ctx.fillStyle = '#FFD400';
      ctx.fillRect(PAD.left + 95, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Consistency', PAD.left + 110, PAD.top + 6);
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.distances.length === 0) return null;
      const { distances, pace_delta, consistency_index } = data;
      const hoverDist = distances[0] + hover.nx * (distances[distances.length - 1] - distances[0] || 1);
      let idx = 0, diff = Infinity;
      for (let i = 0; i < distances.length; i++) {
        const d = Math.abs(distances[i] - hoverDist);
        if (d < diff) { diff = d; idx = i; }
      }
      return {
        header: `${distances[idx].toFixed(0)} m`,
        lines: [
          { label: 'Pace Delta', value: `${pace_delta[idx] >= 0 ? '+' : ''}${pace_delta[idx].toFixed(3)}s`, color: '#B6FF2E' },
          { label: 'Consistency', value: consistency_index[idx].toFixed(3), color: '#FFD400' },
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
    crosshair: true,
  });

  return (
    <ChartPanel title="Performance Trend" subtitle="Pace and consistency over distance" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
