'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface TyreData {
  laps: number[];
  fl_deg: number[];
  fr_deg: number[];
  rl_deg: number[];
  rr_deg: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 15, right: 15, bottom: 30, left: 40 };

const TYRES: { key: keyof TyreData; color: string; label: string }[] = [
  { key: 'fl_deg', color: '#B6FF2E', label: 'FL' },
  { key: 'fr_deg', color: '#FFD400', label: 'FR' },
  { key: 'rl_deg', color: '#FF6A00', label: 'RL' },
  { key: 'rr_deg', color: '#FF2A2A', label: 'RR' },
];

export function TyreChart({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'tyre-data'],
    queryFn: () => api.get<TyreData>(`/sessions/${sessionId}/tyre-data`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.laps.length === 0) return;

      const { laps } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const allVals = TYRES.flatMap((t) => data[t.key] as number[]);
      const maxVal = Math.max(...allVals, 1);

      const toX = (i: number) => PAD.left + (i / (laps.length - 1 || 1)) * plotW;
      const toY = (v: number) => PAD.top + plotH - (v / maxVal) * plotH;

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

      // Y labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        ctx.fillText(`${(maxVal - (i / 4) * maxVal).toFixed(0)}%`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }

      // Lines
      for (const tyre of TYRES) {
        const vals = data[tyre.key] as number[];
        ctx.beginPath();
        ctx.strokeStyle = tyre.color;
        ctx.lineWidth = 1.5;
        for (let i = 0; i < laps.length; i++) {
          const x = toX(i), y = toY(vals[i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // Hover dots
      if (hover) {
        const hoverIdx = Math.round(hover.nx * (laps.length - 1));
        const idx = Math.max(0, Math.min(laps.length - 1, hoverIdx));
        const x = toX(idx);
        for (const tyre of TYRES) {
          const vals = data[tyre.key] as number[];
          ctx.beginPath();
          ctx.arc(x, toY(vals[idx]), 4, 0, Math.PI * 2);
          ctx.fillStyle = tyre.color;
          ctx.fill();
          ctx.strokeStyle = '#F3F0E8';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
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

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      let lx = PAD.left + 5;
      for (const tyre of TYRES) {
        ctx.fillStyle = tyre.color;
        ctx.fillRect(lx, PAD.top + 2, 10, 3);
        ctx.fillStyle = '#8A8F98';
        ctx.fillText(tyre.label, lx + 14, PAD.top + 6);
        lx += 38;
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.laps.length === 0) return null;
      const idx = Math.max(0, Math.min(data.laps.length - 1, Math.round(hover.nx * (data.laps.length - 1))));
      return {
        header: `Lap ${data.laps[idx]}`,
        lines: TYRES.map((t) => ({
          label: t.label,
          value: `${(data[t.key] as number[])[idx].toFixed(1)}%`,
          color: t.color,
        })),
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
    crosshairColor: 'rgba(182, 255, 46, 0.3)',
  });

  return (
    <ChartPanel title="Tyre Degradation" subtitle="Wear per corner over laps" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
