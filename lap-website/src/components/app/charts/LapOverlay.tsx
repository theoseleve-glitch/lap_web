'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface LapOverlayData {
  distances: number[];
  laps: { lap_number: number; speeds: number[] }[];
  best_lap: number;
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 20, right: 15, bottom: 28, left: 50 };

const LAP_COLORS = [
  '#B6FF2E', '#FF6A00', '#FFD400', '#D946EF',
  '#60A5FA', '#34D399', '#F472B6', '#FBBF24',
];

export function LapOverlay({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'lap-overlay'],
    queryFn: () => api.get<LapOverlayData>(`/sessions/${sessionId}/lap-overlay`),
  });

  const range = useMemo(() => {
    if (!data || data.distances.length === 0 || data.laps.length === 0) return null;
    const { distances, laps } = data;
    const allSpeeds = laps.flatMap((l) => l.speeds);
    const maxSpeed = Math.max(...allSpeeds);
    const minSpeed = Math.min(...allSpeeds);
    const speedRange = maxSpeed - minSpeed || 1;
    const minDist = distances[0];
    const maxDist = distances[distances.length - 1];
    const distRange = maxDist - minDist || 1;
    return { maxSpeed, minSpeed, speedRange, minDist, maxDist, distRange };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !range || data.laps.length === 0) return;

      const { distances, laps, best_lap } = data;
      const { minDist, distRange, minSpeed, speedRange, maxSpeed } = range;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const toX = (d: number) => PAD.left + ((d - minDist) / distRange) * plotW;
      const toY = (s: number) => PAD.top + plotH - ((s - minSpeed) / speedRange) * plotH;

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
        ctx.fillText(`${val.toFixed(0)}`, PAD.left - 6, PAD.top + (i / 4) * plotH + 3);
      }

      // Draw non-best laps first (dimmer)
      for (let li = 0; li < laps.length; li++) {
        if (laps[li].lap_number === best_lap) continue;
        const color = LAP_COLORS[li % LAP_COLORS.length];
        ctx.beginPath();
        ctx.strokeStyle = color + '55';
        ctx.lineWidth = 1;
        for (let i = 0; i < distances.length && i < laps[li].speeds.length; i++) {
          const x = toX(distances[i]);
          const y = toY(laps[li].speeds[i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // Draw best lap on top
      for (let li = 0; li < laps.length; li++) {
        if (laps[li].lap_number !== best_lap) continue;
        ctx.beginPath();
        ctx.strokeStyle = '#B6FF2E';
        ctx.lineWidth = 2;
        for (let i = 0; i < distances.length && i < laps[li].speeds.length; i++) {
          const x = toX(distances[i]);
          const y = toY(laps[li].speeds[i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      let lx = PAD.left + 5;
      for (let li = 0; li < Math.min(laps.length, 8); li++) {
        const isBest = laps[li].lap_number === best_lap;
        const color = isBest ? '#B6FF2E' : LAP_COLORS[li % LAP_COLORS.length];
        ctx.fillStyle = color;
        ctx.fillRect(lx, PAD.top + 2, 10, 3);
        ctx.fillStyle = isBest ? '#B6FF2E' : '#8A8F98';
        const label = isBest ? `L${laps[li].lap_number}*` : `L${laps[li].lap_number}`;
        ctx.fillText(label, lx + 14, PAD.top + 6);
        lx += 44;
      }

      // Hover: vertical crosshair + per-lap speed readout
      if (hover && hover.nx >= 0 && hover.nx <= 1) {
        const distIdx = Math.round(hover.nx * (distances.length - 1));
        if (distIdx >= 0 && distIdx < distances.length) {
          // Draw dots on each lap trace at the hovered distance
          for (let li = 0; li < laps.length; li++) {
            if (distIdx >= laps[li].speeds.length) continue;
            const x = toX(distances[distIdx]);
            const y = toY(laps[li].speeds[distIdx]);
            const isBest = laps[li].lap_number === best_lap;
            const color = isBest ? '#B6FF2E' : LAP_COLORS[li % LAP_COLORS.length];
            ctx.beginPath();
            ctx.arc(x, y, 3.5, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.fill();
            ctx.strokeStyle = '#161A20';
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        }
      }
    },
    [data, range],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || !range || data.laps.length === 0) return null;
      const { distances, laps, best_lap } = data;
      const distIdx = Math.round(hover.nx * (distances.length - 1));
      if (distIdx < 0 || distIdx >= distances.length) return null;

      const dist = distances[distIdx];
      const lines = laps
        .filter((l) => distIdx < l.speeds.length)
        .map((l) => {
          const isBest = l.lap_number === best_lap;
          const li = laps.indexOf(l);
          return {
            label: `L${l.lap_number}${isBest ? '*' : ''}`,
            value: `${l.speeds[distIdx].toFixed(1)} km/h`,
            color: isBest ? '#B6FF2E' : LAP_COLORS[li % LAP_COLORS.length],
          };
        });

      return {
        header: `${(dist / 1000).toFixed(2)} km`,
        lines,
      };
    },
    [data, range],
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
      <ChartPanel title="Lap Overlay">
        <div className={`${height} flex items-center justify-center`}>
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </ChartPanel>
    );

  if (!data || data.laps.length === 0)
    return (
      <ChartPanel title="Lap Overlay">
        <div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>
          No data available
        </div>
      </ChartPanel>
    );

  return (
    <ChartPanel title="Lap Overlay" subtitle="Multi-lap speed comparison">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
