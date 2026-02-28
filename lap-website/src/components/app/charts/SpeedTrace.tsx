'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface SpeedTraceData {
  distances: number[];
  speeds: number[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 12, right: 15, bottom: 28, left: 50 };

export function SpeedTrace({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'speed-trace'],
    queryFn: () => api.get<SpeedTraceData>(`/sessions/${sessionId}/speed-trace`),
  });

  const range = useMemo(() => {
    if (!data || data.distances.length === 0) return null;
    const { distances, speeds } = data;
    const minDist = distances[0];
    const maxDist = distances[distances.length - 1];
    const distRange = maxDist - minDist || 1;
    const maxSpeed = Math.max(...speeds);
    const minSpeed = Math.min(...speeds);
    const speedRange = maxSpeed - minSpeed || 1;
    return { minDist, maxDist, distRange, minSpeed, maxSpeed, speedRange };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !range || data.distances.length === 0) return;

      const { distances, speeds } = data;
      const { minDist, distRange, minSpeed, maxSpeed, speedRange } = range;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const toX = (d: number) => PAD.left + ((d - minDist) / distRange) * plotW;
      const toY = (s: number) => PAD.top + plotH - ((s - minSpeed) / speedRange) * plotH;

      // Grid lines
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + plotW, y);
        ctx.stroke();
      }

      // Y-axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const val = maxSpeed - (i / 4) * speedRange;
        const y = PAD.top + (i / 4) * plotH;
        ctx.fillText(`${val.toFixed(0)}`, PAD.left - 6, y + 3);
      }

      // X-axis labels
      ctx.textAlign = 'center';
      for (let i = 0; i <= 4; i++) {
        const val = minDist + (i / 4) * distRange;
        const x = PAD.left + (i / 4) * plotW;
        ctx.fillText(`${(val / 1000).toFixed(1)}km`, x, h - 5);
      }

      // Speed trace line
      ctx.beginPath();
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 1.5;
      ctx.lineJoin = 'round';

      for (let i = 0; i < distances.length; i++) {
        const x = toX(distances[i]);
        const y = toY(speeds[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Fill under curve
      ctx.lineTo(PAD.left + plotW, PAD.top + plotH);
      ctx.lineTo(PAD.left, PAD.top + plotH);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + plotH);
      grad.addColorStop(0, '#B6FF2E22');
      grad.addColorStop(1, '#B6FF2E02');
      ctx.fillStyle = grad;
      ctx.fill();

      // Hover: draw highlighted point
      if (hover && hover.nx >= 0 && hover.nx <= 1) {
        const idx = Math.round(hover.nx * (distances.length - 1));
        if (idx >= 0 && idx < distances.length) {
          const hx = toX(distances[idx]);
          const hy = toY(speeds[idx]);

          // Dot
          ctx.beginPath();
          ctx.arc(hx, hy, 4, 0, Math.PI * 2);
          ctx.fillStyle = '#B6FF2E';
          ctx.fill();
          ctx.strokeStyle = '#161A20';
          ctx.lineWidth = 1.5;
          ctx.stroke();

          // Horizontal guide line to Y axis
          ctx.save();
          ctx.strokeStyle = 'rgba(182, 255, 46, 0.2)';
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(PAD.left, hy);
          ctx.lineTo(hx, hy);
          ctx.stroke();
          ctx.restore();
        }
      }
    },
    [data, range],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.distances.length === 0) return null;
      const idx = Math.round(hover.nx * (data.distances.length - 1));
      if (idx < 0 || idx >= data.distances.length) return null;
      const dist = data.distances[idx];
      const speed = data.speeds[idx];
      return {
        header: `${(dist / 1000).toFixed(2)} km`,
        lines: [
          { label: 'Speed', value: `${speed.toFixed(1)} km/h`, color: '#B6FF2E' },
        ],
      };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, range],
    padding: PAD,
    getTooltipData,
    crosshair: true,
  });

  if (isLoading)
    return (
      <ChartPanel title="Speed Trace">
        <div className={`${height} flex items-center justify-center`}>
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </ChartPanel>
    );

  if (!data || data.distances.length === 0)
    return (
      <ChartPanel title="Speed Trace">
        <div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>
          No data available
        </div>
      </ChartPanel>
    );

  return (
    <ChartPanel title="Speed Trace" subtitle="Speed over distance">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
