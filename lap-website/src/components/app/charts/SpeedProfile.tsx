'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface SpeedProfileData {
  distances: number[];
  best_lap: number[];
  average: number[];
  worst_lap: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 15, right: 15, bottom: 30, left: 45 };

const LINES: { key: keyof SpeedProfileData; color: string; label: string; width: number }[] = [
  { key: 'worst_lap', color: '#FF2A2A66', label: 'Worst', width: 1 },
  { key: 'average', color: '#FFD40099', label: 'Avg', width: 1 },
  { key: 'best_lap', color: '#B6FF2E', label: 'Best', width: 2 },
];

export function SpeedProfile({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'speed-profile'],
    queryFn: () => api.get<SpeedProfileData>(`/sessions/${sessionId}/speed-profile`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.distances.length === 0) return;

      const { distances, best_lap, average, worst_lap } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const allSpeeds = [...best_lap, ...average, ...worst_lap];
      const maxSpeed = Math.max(...allSpeeds), minSpeed = Math.min(...allSpeeds);
      const sR = maxSpeed - minSpeed || 1;
      const minDist = distances[0], maxDist = distances[distances.length - 1];
      const dR = maxDist - minDist || 1;

      const toX = (d: number) => PAD.left + ((d - minDist) / dR) * plotW;
      const toY = (s: number) => PAD.top + plotH - ((s - minSpeed) / sR) * plotH;

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
        ctx.fillText(`${(maxSpeed - (i / 4) * sR).toFixed(0)}`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }

      // Fill between best and worst
      ctx.beginPath();
      for (let i = 0; i < distances.length; i++) {
        const x = toX(distances[i]);
        if (i === 0) ctx.moveTo(x, toY(best_lap[i]));
        else ctx.lineTo(x, toY(best_lap[i]));
      }
      for (let i = distances.length - 1; i >= 0; i--) {
        ctx.lineTo(toX(distances[i]), toY(worst_lap[i]));
      }
      ctx.closePath();
      ctx.fillStyle = 'rgba(138, 143, 152, 0.08)';
      ctx.fill();

      // Draw lines
      for (const line of LINES) {
        const vals = data[line.key] as number[];
        ctx.beginPath();
        ctx.strokeStyle = line.color;
        ctx.lineWidth = line.width;
        for (let i = 0; i < distances.length; i++) {
          const x = toX(distances[i]), y = toY(vals[i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // Hover dots
      if (hover) {
        const hoverDist = minDist + hover.nx * dR;
        let nearIdx = 0, nearDiff = Infinity;
        for (let i = 0; i < distances.length; i++) {
          const diff = Math.abs(distances[i] - hoverDist);
          if (diff < nearDiff) { nearDiff = diff; nearIdx = i; }
        }
        const channels: [number[], string][] = [
          [best_lap, '#B6FF2E'], [average, '#FFD400'], [worst_lap, '#FF2A2A'],
        ];
        for (const [vals, color] of channels) {
          ctx.beginPath();
          ctx.arc(toX(distances[nearIdx]), toY(vals[nearIdx]), 4, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();
          ctx.strokeStyle = '#F3F0E8';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#B6FF2E';
      ctx.fillRect(PAD.left + 5, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Best', PAD.left + 20, PAD.top + 6);
      ctx.fillStyle = '#FFD400';
      ctx.fillRect(PAD.left + 55, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Avg', PAD.left + 70, PAD.top + 6);
      ctx.fillStyle = '#FF2A2A';
      ctx.fillRect(PAD.left + 100, PAD.top + 2, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Worst', PAD.left + 115, PAD.top + 6);
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.distances.length === 0) return null;
      const { distances, best_lap, average, worst_lap } = data;
      const hoverDist = distances[0] + hover.nx * (distances[distances.length - 1] - distances[0] || 1);
      let idx = 0, diff = Infinity;
      for (let i = 0; i < distances.length; i++) {
        const d = Math.abs(distances[i] - hoverDist);
        if (d < diff) { diff = d; idx = i; }
      }
      return {
        header: `${distances[idx].toFixed(0)} m`,
        lines: [
          { label: 'Best', value: `${best_lap[idx].toFixed(1)} m/s`, color: '#B6FF2E' },
          { label: 'Average', value: `${average[idx].toFixed(1)} m/s`, color: '#FFD400' },
          { label: 'Worst', value: `${worst_lap[idx].toFixed(1)} m/s`, color: '#FF2A2A' },
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
    <ChartPanel title="Speed Profile" subtitle="Best / avg / worst overlay" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
