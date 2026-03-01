'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface RivalGapData {
  laps: number[];
  gap: number[];
  rival_name: string;
}

interface Props {
  sessionId: string;
}

const PAD = { top: 10, right: 15, bottom: 30, left: 45 };

export function RivalChart({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'rival-gap'],
    queryFn: () => api.get<RivalGapData>(`/sessions/${sessionId}/rival-gap`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.laps.length === 0) return;

      const { laps, gap } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const cleanGap = gap.filter(Number.isFinite).map(Math.abs);
      const maxGap = cleanGap.length > 0 ? Math.max(...cleanGap, 0.1) : 0.1;
      const cy = PAD.top + plotH / 2;

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

      // Zero line
      ctx.beginPath();
      ctx.strokeStyle = '#8A8F98';
      ctx.lineWidth = 1;
      ctx.moveTo(PAD.left, cy);
      ctx.lineTo(PAD.left + plotW, cy);
      ctx.stroke();

      // Y labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`+${maxGap.toFixed(1)}s`, PAD.left - 5, PAD.top + 4);
      ctx.fillText(`-${maxGap.toFixed(1)}s`, PAD.left - 5, PAD.top + plotH + 4);
      ctx.fillText('0.0s', PAD.left - 5, cy + 4);

      const toX = (i: number) => PAD.left + (i / (laps.length - 1 || 1)) * plotW;
      const toY = (g: number) => { const safe = Number.isFinite(g) ? g : 0; const v = cy - (safe / maxGap) * (plotH / 2); return Number.isFinite(v) ? v : cy; };

      // Gradient fill
      ctx.beginPath();
      for (let i = 0; i < laps.length; i++) {
        const x = toX(i), y = toY(gap[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.lineTo(toX(laps.length - 1), cy);
      ctx.lineTo(toX(0), cy);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + plotH);
      grad.addColorStop(0, '#B6FF2E33');
      grad.addColorStop(0.5, 'transparent');
      grad.addColorStop(1, '#FF2A2A33');
      ctx.fillStyle = grad;
      ctx.fill();

      // Gap line
      ctx.beginPath();
      ctx.strokeStyle = '#F3F0E8';
      ctx.lineWidth = 2;
      for (let i = 0; i < laps.length; i++) {
        const x = toX(i), y = toY(gap[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Hover dot
      if (hover) {
        const idx = Math.max(0, Math.min(laps.length - 1, Math.round(hover.nx * (laps.length - 1))));
        ctx.beginPath();
        ctx.arc(toX(idx), toY(gap[idx]), 5, 0, Math.PI * 2);
        ctx.fillStyle = gap[idx] >= 0 ? '#B6FF2E' : '#FF2A2A';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // X-axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      for (let i = 0; i < laps.length; i++) {
        if (laps.length <= 15 || i % Math.ceil(laps.length / 10) === 0) {
          ctx.fillText(`L${laps[i]}`, toX(i), h - 8);
        }
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.laps.length === 0) return null;
      const idx = Math.max(0, Math.min(data.laps.length - 1, Math.round(hover.nx * (data.laps.length - 1))));
      const g = data.gap[idx];
      return {
        header: `Lap ${data.laps[idx]}`,
        lines: [
          {
            label: g >= 0 ? 'Ahead' : 'Behind',
            value: `${g >= 0 ? '+' : ''}${g.toFixed(3)}s`,
            color: g >= 0 ? '#B6FF2E' : '#FF2A2A',
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
    crosshair: true,
  });

  const subtitle = data?.rival_name ? `Gap to ${data.rival_name}` : 'Rival gap analysis';

  return (
    <ChartPanel title="Rival Gap" subtitle={subtitle} loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
