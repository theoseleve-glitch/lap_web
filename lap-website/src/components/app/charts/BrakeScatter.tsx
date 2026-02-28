'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface BrakePointData {
  distances: number[];
  speeds: number[];
  pressures: number[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 10, right: 15, bottom: 30, left: 45 };

export function BrakeScatter({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'brake-points'],
    queryFn: () => api.get<BrakePointData>(`/sessions/${sessionId}/brake-points`),
  });

  const stats = useMemo(() => {
    if (!data || data.distances.length === 0) return null;
    const minDist = Math.min(...data.distances);
    const maxDist = Math.max(...data.distances);
    const distRange = maxDist - minDist || 1;
    const minSpeed = Math.min(...data.speeds);
    const maxSpeed = Math.max(...data.speeds);
    const speedRange = maxSpeed - minSpeed || 1;
    const maxPressure = Math.max(...data.pressures, 1);
    return { minDist, maxDist, distRange, minSpeed, maxSpeed, speedRange, maxPressure };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !stats || data.distances.length === 0) return;

      const { distances, speeds, pressures } = data;
      const { minDist, distRange, minSpeed, maxSpeed, speedRange, maxPressure } = stats;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

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

      // Y-axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const val = maxSpeed - (i / 4) * speedRange;
        ctx.fillText(`${val.toFixed(0)}`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }
      ctx.textAlign = 'center';
      ctx.fillText('Distance (m)', w / 2, h - 3);

      // Find nearest point to hover
      let nearestIdx = -1;
      if (hover) {
        let minD = Infinity;
        for (let i = 0; i < distances.length; i++) {
          const px = PAD.left + ((distances[i] - minDist) / distRange) * plotW;
          const py = PAD.top + plotH - ((speeds[i] - minSpeed) / speedRange) * plotH;
          const d = (hover.x - px) ** 2 + (hover.y - py) ** 2;
          if (d < minD) { minD = d; nearestIdx = i; }
        }
        if (minD > 600) nearestIdx = -1;
      }

      // Scatter points
      for (let i = 0; i < distances.length; i++) {
        const x = PAD.left + ((distances[i] - minDist) / distRange) * plotW;
        const y = PAD.top + plotH - ((speeds[i] - minSpeed) / speedRange) * plotH;
        const r = 2 + (pressures[i] / maxPressure) * 5;

        const isHovered = i === nearestIdx;
        ctx.beginPath();
        ctx.arc(x, y, isHovered ? r + 2 : r, 0, Math.PI * 2);
        ctx.fillStyle = isHovered ? '#FF5555' : '#FF2A2A99';
        ctx.fill();
        ctx.strokeStyle = isHovered ? '#FF2A2A' : '#FF2A2A66';
        ctx.lineWidth = isHovered ? 1.5 : 0.5;
        ctx.stroke();
      }
    },
    [data, stats],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || !stats || data.distances.length === 0) return null;
      const { distances, speeds, pressures } = data;
      const { minDist, distRange, minSpeed, speedRange, maxPressure } = stats;

      let nearestIdx = -1;
      let minD = Infinity;
      for (let i = 0; i < distances.length; i += 2) {
        const dist = Math.abs(hover.nx - ((distances[i] - minDist) / distRange)) ** 2 +
                     Math.abs(hover.ny - (1 - (speeds[i] - minSpeed) / speedRange)) ** 2;
        if (dist < minD) { minD = dist; nearestIdx = i; }
      }
      if (nearestIdx < 0 || minD > 0.05) return null;

      return {
        header: `Brake Point`,
        lines: [
          { label: 'Distance', value: `${distances[nearestIdx].toFixed(0)}m` },
          { label: 'Speed', value: `${speeds[nearestIdx].toFixed(0)} km/h`, color: '#FFD400' },
          { label: 'Pressure', value: `${((pressures[nearestIdx] / maxPressure) * 100).toFixed(0)}%`, color: '#FF2A2A' },
        ],
      };
    },
    [data, stats],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, stats],
    padding: PAD,
    getTooltipData,
  });

  if (isLoading) return <ChartPanel title="Brake Points"><div className={`${height} flex items-center justify-center`}><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.distances.length === 0) return <ChartPanel title="Brake Points"><div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Brake Points" subtitle="Brake point scatter by distance">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
