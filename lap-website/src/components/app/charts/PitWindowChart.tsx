'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface PitWindowData {
  laps: number[];
  cumulative_time: number[];
  optimal_pit_lap: number | null;
  pit_window_start: number | null;
  pit_window_end: number | null;
}

interface Props {
  sessionId: string;
}

const PAD = { top: 10, right: 15, bottom: 30, left: 50 };

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}:${sec.toFixed(1).padStart(4, '0')}` : `${sec.toFixed(1)}s`;
}

export function PitWindowChart({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'pit-window'],
    queryFn: () => api.get<PitWindowData>(`/sessions/${sessionId}/pit-window`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.laps.length === 0) return;

      const { laps, cumulative_time, optimal_pit_lap, pit_window_start, pit_window_end } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const cleanTime = cumulative_time.filter(Number.isFinite);
      const maxTime = cleanTime.length > 0 ? Math.max(...cleanTime, 1) : 1;
      const minLap = laps[0], maxLap = laps[laps.length - 1];
      const lapR = maxLap - minLap || 1;

      const toX = (lap: number) => { const v = PAD.left + ((lap - minLap) / lapR) * plotW; return Number.isFinite(v) ? v : PAD.left; };
      const toY = (t: number) => { const v = PAD.top + plotH - ((Number.isFinite(t) ? t : 0) / maxTime) * plotH; return Number.isFinite(v) ? v : PAD.top; };

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

      // Pit window highlight
      if (pit_window_start != null && pit_window_end != null) {
        const x1 = toX(pit_window_start), x2 = toX(pit_window_end);
        ctx.fillStyle = '#B6FF2E11';
        ctx.fillRect(x1, PAD.top, x2 - x1, plotH);
        ctx.strokeStyle = '#B6FF2E44';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x1, PAD.top);
        ctx.lineTo(x1, PAD.top + plotH);
        ctx.moveTo(x2, PAD.top);
        ctx.lineTo(x2, PAD.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#B6FF2E';
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText('PIT WINDOW', (x1 + x2) / 2, PAD.top + 12);
      }

      // Cumulative time line
      ctx.beginPath();
      ctx.strokeStyle = '#F3F0E8';
      ctx.lineWidth = 2;
      for (let i = 0; i < laps.length; i++) {
        const x = toX(laps[i]), y = toY(cumulative_time[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Optimal pit marker
      if (optimal_pit_lap != null) {
        const ox = toX(optimal_pit_lap);
        ctx.beginPath();
        ctx.arc(ox, PAD.top + plotH * 0.3, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        ctx.fillStyle = '#B6FF2E';
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`Opt: L${optimal_pit_lap}`, ox, PAD.top + plotH * 0.3 - 10);
      }

      // Hover dot
      if (hover) {
        const idx = Math.max(0, Math.min(laps.length - 1, Math.round(hover.nx * (laps.length - 1))));
        ctx.beginPath();
        ctx.arc(toX(laps[idx]), toY(cumulative_time[idx]), 5, 0, Math.PI * 2);
        ctx.fillStyle = '#FF6A00';
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
          ctx.fillText(`L${laps[i]}`, toX(laps[i]), h - 8);
        }
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.laps.length === 0) return null;
      const idx = Math.max(0, Math.min(data.laps.length - 1, Math.round(hover.nx * (data.laps.length - 1))));
      const inWindow = data.pit_window_start != null && data.pit_window_end != null
        && data.laps[idx] >= data.pit_window_start && data.laps[idx] <= data.pit_window_end;
      const lines: TooltipData['lines'] = [
        { label: 'Cumulative', value: fmtTime(data.cumulative_time[idx]), color: '#F3F0E8' },
      ];
      if (inWindow) {
        lines.push({ label: 'Status', value: 'In pit window', color: '#B6FF2E' });
      }
      if (data.optimal_pit_lap === data.laps[idx]) {
        lines.push({ label: 'Optimal', value: 'Best pit lap', color: '#B6FF2E' });
      }
      return { header: `Lap ${data.laps[idx]}`, lines };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data],
    padding: PAD,
    getTooltipData,
    crosshair: true,
    crosshairColor: 'rgba(255, 106, 0, 0.3)',
  });

  return (
    <ChartPanel title="Pit Window" subtitle="Optimal pit stop timing" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
