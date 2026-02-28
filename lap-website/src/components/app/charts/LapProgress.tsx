'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface LapData {
  laps: { lap_number: number; time: number; valid: boolean }[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 12, right: 15, bottom: 28, left: 55 };

function formatLapTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(3);
  return `${m}:${sec.padStart(6, '0')}`;
}

export function LapProgress({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'laps-chart'],
    queryFn: () => api.get<LapData>(`/sessions/${sessionId}/laps`),
  });

  const layout = useMemo(() => {
    if (!data || data.laps.length === 0) return null;
    const times = data.laps.map((l) => l.time);
    const maxTime = Math.max(...times);
    const minTime = Math.min(...times);
    const timeRange = maxTime - minTime || 1;
    const bestIdx = times.indexOf(minTime);
    return { times, maxTime, minTime, timeRange, bestIdx };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !layout || data.laps.length === 0) return;

      const { laps } = data;
      const { minTime, timeRange, bestIdx, maxTime } = layout;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const barW = Math.min(30, (plotW / laps.length) * 0.7);
      const gap = (plotW - barW * laps.length) / (laps.length + 1);

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
        const val = maxTime - (i / 4) * timeRange;
        const y = PAD.top + (i / 4) * plotH;
        const m = Math.floor(val / 60);
        const s = (val % 60).toFixed(1);
        ctx.fillText(`${m}:${s.padStart(4, '0')}`, PAD.left - 6, y + 3);
      }

      // Hovered bar index
      const hoveredIdx = hover
        ? Math.floor((hover.x - PAD.left - gap) / (barW + gap))
        : -1;

      // Mean line
      const mean = laps.reduce((a, l) => a + l.time, 0) / laps.length;
      const meanY = PAD.top + plotH - ((mean - minTime) / timeRange) * plotH * 0.85 - plotH * 0.15;
      ctx.save();
      ctx.strokeStyle = 'rgba(255, 212, 0, 0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(PAD.left, meanY);
      ctx.lineTo(PAD.left + plotW, meanY);
      ctx.stroke();
      ctx.restore();
      // Mean label
      ctx.fillStyle = '#FFD400';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText('Mean', PAD.left + plotW + 3, meanY + 3);

      // Bars
      for (let i = 0; i < laps.length; i++) {
        const barH = ((laps[i].time - minTime) / timeRange) * plotH * 0.85 + plotH * 0.15;
        const x = PAD.left + gap + i * (barW + gap);
        const y = PAD.top + plotH - barH;

        // Bar color: best=bright green, invalid=red, hovered=brighter, normal=green/60%
        let barColor: string;
        if (i === bestIdx) {
          barColor = i === hoveredIdx ? '#D4FF70' : '#B6FF2E';
        } else if (!laps[i].valid) {
          barColor = i === hoveredIdx ? '#FF5555' : '#FF2A2A88';
        } else {
          barColor = i === hoveredIdx ? '#B6FF2EAA' : '#B6FF2E66';
        }

        ctx.fillStyle = barColor;
        ctx.fillRect(x, y, barW, barH);

        // Lap number label
        ctx.fillStyle = i === hoveredIdx ? '#F3F0E8' : '#8A8F98';
        ctx.font = i === hoveredIdx ? 'bold 9px "IBM Plex Mono", monospace' : '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`${laps[i].lap_number}`, x + barW / 2, h - 8);

        // Best badge
        if (i === bestIdx) {
          ctx.fillStyle = '#B6FF2E';
          ctx.font = 'bold 8px "IBM Plex Mono", monospace';
          ctx.fillText('BEST', x + barW / 2, y - 4);
        }
      }
    },
    [data, layout],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.laps.length === 0) return null;

      // Find which bar the cursor is over
      const idx = Math.floor(hover.nx * data.laps.length);
      if (idx < 0 || idx >= data.laps.length) return null;

      const lap = data.laps[idx];
      const isBest = layout ? idx === layout.bestIdx : false;
      return {
        header: `Lap ${lap.lap_number}${isBest ? ' (BEST)' : ''}${!lap.valid ? ' (INVALID)' : ''}`,
        lines: [
          { label: 'Time', value: formatLapTime(lap.time), color: isBest ? '#B6FF2E' : '#F3F0E8' },
          { label: 'Delta', value: layout ? `+${(lap.time - layout.minTime).toFixed(3)}s` : '--', color: '#FFD400' },
        ],
      };
    },
    [data, layout],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, layout],
    padding: PAD,
    getTooltipData,
  });

  if (isLoading)
    return (
      <ChartPanel title="Lap Progress">
        <div className={`${height} flex items-center justify-center`}>
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </ChartPanel>
    );

  if (!data || data.laps.length === 0)
    return (
      <ChartPanel title="Lap Progress">
        <div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>
          No data available
        </div>
      </ChartPanel>
    );

  return (
    <ChartPanel title="Lap Progress" subtitle="Lap times across session">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
