'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface FatigueData {
  laps: number[];
  fatigue_index: number[];
  reaction_time: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 15, right: 45, bottom: 30, left: 45 };

export function FatigueChart({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'fatigue'],
    queryFn: () => api.get<FatigueData>(`/sessions/${sessionId}/fatigue`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.laps.length === 0) return;

      const { laps, fatigue_index, reaction_time } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const cleanF = fatigue_index.filter(Number.isFinite);
      const cleanR = reaction_time.filter(Number.isFinite);
      const maxF = cleanF.length > 0 ? Math.max(...cleanF, 0.1) : 0.1;
      const maxR = cleanR.length > 0 ? Math.max(...cleanR, 0.1) : 0.1;

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

      // Left Y-axis labels (fatigue)
      ctx.fillStyle = '#FFD400';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        ctx.fillText(`${(maxF - (i / 4) * maxF).toFixed(1)}`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }

      // Right Y-axis labels (reaction)
      ctx.fillStyle = '#FF6A00';
      ctx.textAlign = 'left';
      for (let i = 0; i <= 4; i++) {
        ctx.fillText(`${(maxR - (i / 4) * maxR).toFixed(2)}s`, PAD.left + plotW + 5, PAD.top + (i / 4) * plotH + 3);
      }

      const toX = (idx: number) => PAD.left + (idx / (laps.length - 1 || 1)) * plotW;

      const safeY = (val: number, maxVal: number) => {
        const v = PAD.top + plotH - ((Number.isFinite(val) ? val : 0) / maxVal) * plotH;
        return Number.isFinite(v) ? v : PAD.top;
      };

      // Fatigue line
      ctx.beginPath();
      ctx.strokeStyle = '#FFD400';
      ctx.lineWidth = 2;
      for (let i = 0; i < laps.length; i++) {
        const x = toX(i), y = safeY(fatigue_index[i], maxF);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Reaction time line
      ctx.beginPath();
      ctx.strokeStyle = '#FF6A00';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      for (let i = 0; i < laps.length; i++) {
        const x = toX(i), y = safeY(reaction_time[i], maxR);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Hover dots
      if (hover) {
        const hoverIdx = Math.round(hover.nx * (laps.length - 1));
        const idx = Math.max(0, Math.min(laps.length - 1, hoverIdx));
        const x = toX(idx);
        // Fatigue dot
        ctx.beginPath();
        ctx.arc(x, safeY(fatigue_index[idx], maxF), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#FFD400';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        // Reaction dot
        ctx.beginPath();
        ctx.arc(x, safeY(reaction_time[idx], maxR), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#FF6A00';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // X-axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      for (let i = 0; i < laps.length; i++) {
        if (laps.length <= 20 || i % Math.ceil(laps.length / 10) === 0) {
          ctx.fillText(`L${laps[i]}`, toX(i), h - 8);
        }
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#FFD400';
      ctx.fillRect(PAD.left + 5, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Fatigue', PAD.left + 20, PAD.top + 6);
      ctx.fillStyle = '#FF6A00';
      ctx.fillRect(PAD.left + 80, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Reaction', PAD.left + 95, PAD.top + 6);
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.laps.length === 0) return null;
      const idx = Math.max(0, Math.min(data.laps.length - 1, Math.round(hover.nx * (data.laps.length - 1))));
      return {
        header: `Lap ${data.laps[idx]}`,
        lines: [
          { label: 'Fatigue', value: data.fatigue_index[idx].toFixed(2), color: '#FFD400' },
          { label: 'Reaction', value: `${data.reaction_time[idx].toFixed(3)}s`, color: '#FF6A00' },
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
    crosshairColor: 'rgba(255, 212, 0, 0.3)',
  });

  return (
    <ChartPanel title="Fatigue Trend" subtitle="Driver fatigue over session" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
