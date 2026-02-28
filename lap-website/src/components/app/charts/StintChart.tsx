'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface StintData {
  stints: {
    stint_number: number;
    start_lap: number;
    end_lap: number;
    avg_time: number;
    best_time: number;
    laps_count: number;
  }[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 15, right: 15, bottom: 35, left: 50 };

function formatLapTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(3);
  return `${m}:${sec.padStart(6, '0')}`;
}

export function StintChart({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'stints'],
    queryFn: () => api.get<StintData>(`/sessions/${sessionId}/stints`),
  });

  const layout = useMemo(() => {
    if (!data || data.stints.length === 0) return null;
    const allTimes = data.stints.flatMap((s) => [s.avg_time, s.best_time]);
    const maxTime = Math.max(...allTimes);
    const minTime = Math.min(...allTimes);
    const timeRange = maxTime - minTime || 1;
    return { maxTime, minTime, timeRange };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !layout || data.stints.length === 0) return;

      const { stints } = data;
      const { minTime, timeRange, maxTime } = layout;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const groupW = plotW / stints.length;
      const barW = Math.min(40, groupW * 0.6);

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

      // Y-axis
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        const val = maxTime - (i / 4) * timeRange;
        const m = Math.floor(val / 60);
        const s = (val % 60).toFixed(1);
        ctx.fillText(`${m}:${s.padStart(4, '0')}`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }

      // Hovered stint index
      const hoveredIdx = hover
        ? Math.floor((hover.x - PAD.left) / groupW)
        : -1;

      for (let i = 0; i < stints.length; i++) {
        const cx = PAD.left + i * groupW + groupW / 2;
        const s = stints[i];
        const isHovered = i === hoveredIdx && hoveredIdx >= 0 && hoveredIdx < stints.length;

        // Avg time bar
        const avgH = ((s.avg_time - minTime) / timeRange) * plotH * 0.85 + plotH * 0.15;
        ctx.fillStyle = isHovered ? '#FFD400CC' : '#FFD40066';
        ctx.fillRect(cx - barW / 2, PAD.top + plotH - avgH, barW / 2 - 1, avgH);

        // Best time bar
        const bestH = ((s.best_time - minTime) / timeRange) * plotH * 0.85 + plotH * 0.15;
        ctx.fillStyle = isHovered ? '#B6FF2E' : '#B6FF2EAA';
        ctx.fillRect(cx + 1, PAD.top + plotH - bestH, barW / 2 - 1, bestH);

        // Label
        ctx.fillStyle = isHovered ? '#F3F0E8' : '#8A8F98';
        ctx.font = isHovered ? 'bold 9px "IBM Plex Mono", monospace' : '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`S${s.stint_number}`, cx, h - 18);
        ctx.fillStyle = '#8A8F9880';
        ctx.font = '8px "IBM Plex Mono", monospace';
        ctx.fillText(`${s.laps_count}L`, cx, h - 7);
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#FFD400';
      ctx.fillRect(PAD.left + 5, PAD.top + 3, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Avg', PAD.left + 20, PAD.top + 7);
      ctx.fillStyle = '#B6FF2E';
      ctx.fillRect(PAD.left + 50, PAD.top + 3, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Best', PAD.left + 65, PAD.top + 7);
    },
    [data, layout],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.stints.length === 0) return null;

      const idx = Math.floor(hover.nx * data.stints.length);
      if (idx < 0 || idx >= data.stints.length) return null;

      const s = data.stints[idx];
      return {
        header: `Stint ${s.stint_number}`,
        lines: [
          { label: 'Laps', value: `${s.start_lap}–${s.end_lap} (${s.laps_count})` },
          { label: 'Best', value: formatLapTime(s.best_time), color: '#B6FF2E' },
          { label: 'Avg', value: formatLapTime(s.avg_time), color: '#FFD400' },
          { label: 'Gap', value: `+${(s.avg_time - s.best_time).toFixed(3)}s`, color: '#8A8F98' },
        ],
      };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, layout],
    padding: PAD,
    getTooltipData,
  });

  if (isLoading) return <ChartPanel title="Stint Analysis"><div className={`${height} flex items-center justify-center`}><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.stints.length === 0) return <ChartPanel title="Stint Analysis"><div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Stint Analysis" subtitle="Performance breakdown by stint">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
