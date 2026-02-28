'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface WorkloadData {
  timestamps: number[];
  steering: number[];
  braking: number[];
  throttle: number[];
  total: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 15, right: 15, bottom: 25, left: 40 };

const CHANNELS: { key: keyof WorkloadData; color: string; label: string }[] = [
  { key: 'steering', color: '#FFD400', label: 'Steer' },
  { key: 'braking', color: '#FF2A2A', label: 'Brake' },
  { key: 'throttle', color: '#B6FF2E', label: 'Throttle' },
];

export function WorkloadChart({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'workload'],
    queryFn: () => api.get<WorkloadData>(`/sessions/${sessionId}/workload`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.timestamps.length === 0) return;

      const { timestamps, total } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const maxVal = Math.max(...total, 0.01);
      const minT = timestamps[0], maxT = timestamps[timestamps.length - 1];
      const tR = maxT - minT || 1;

      const toX = (t: number) => PAD.left + ((t - minT) / tR) * plotW;
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

      // Channel lines
      for (const ch of CHANNELS) {
        const vals = data[ch.key] as number[];
        ctx.beginPath();
        for (let i = 0; i < timestamps.length; i++) {
          const x = toX(timestamps[i]), y = toY(vals[i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = ch.color;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Total workload line
      ctx.beginPath();
      ctx.strokeStyle = '#F3F0E8';
      ctx.lineWidth = 2;
      for (let i = 0; i < timestamps.length; i++) {
        const x = toX(timestamps[i]), y = toY(total[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Hover dots
      if (hover) {
        const hoverT = minT + hover.nx * tR;
        let idx = 0, diff = Infinity;
        for (let i = 0; i < timestamps.length; i++) {
          const d = Math.abs(timestamps[i] - hoverT);
          if (d < diff) { diff = d; idx = i; }
        }
        const x = toX(timestamps[idx]);
        for (const ch of CHANNELS) {
          const vals = data[ch.key] as number[];
          ctx.beginPath();
          ctx.arc(x, toY(vals[idx]), 3, 0, Math.PI * 2);
          ctx.fillStyle = ch.color;
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(x, toY(total[idx]), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#F3F0E8';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      let lx = PAD.left + 5;
      for (const ch of CHANNELS) {
        ctx.fillStyle = ch.color;
        ctx.fillRect(lx, PAD.top + 2, 10, 3);
        ctx.fillStyle = '#8A8F98';
        ctx.fillText(ch.label, lx + 14, PAD.top + 6);
        lx += 60;
      }
      ctx.fillStyle = '#F3F0E8';
      ctx.fillRect(lx, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Total', lx + 14, PAD.top + 6);
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.timestamps.length === 0) return null;
      const { timestamps, steering, braking, throttle, total } = data;
      const hoverT = timestamps[0] + hover.nx * (timestamps[timestamps.length - 1] - timestamps[0] || 1);
      let idx = 0, diff = Infinity;
      for (let i = 0; i < timestamps.length; i++) {
        const d = Math.abs(timestamps[i] - hoverT);
        if (d < diff) { diff = d; idx = i; }
      }
      return {
        header: `${timestamps[idx].toFixed(1)}s`,
        lines: [
          { label: 'Total', value: total[idx].toFixed(2), color: '#F3F0E8' },
          { label: 'Steer', value: steering[idx].toFixed(2), color: '#FFD400' },
          { label: 'Brake', value: braking[idx].toFixed(2), color: '#FF2A2A' },
          { label: 'Throttle', value: throttle[idx].toFixed(2), color: '#B6FF2E' },
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
    crosshairColor: 'rgba(243, 240, 232, 0.3)',
  });

  return (
    <ChartPanel title="Driver Workload" subtitle="Input workload over time" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
