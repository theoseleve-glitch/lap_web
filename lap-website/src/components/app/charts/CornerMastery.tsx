'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface CornerMasteryData {
  corners: {
    name: string;
    score: number;
    entry_speed: number;
    apex_speed: number;
    exit_speed: number;
  }[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 15, right: 15, bottom: 30, left: 55 };

export function CornerMastery({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'corner-mastery'],
    queryFn: () => api.get<CornerMasteryData>(`/sessions/${sessionId}/corner-mastery`),
  });

  const cornerCount = useMemo(() => data?.corners.length ?? 0, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.corners.length === 0) return;

      const { corners } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const rowH = Math.min(22, plotH / corners.length);

      // Hovered row index
      const hoveredIdx = hover
        ? Math.floor((hover.y - PAD.top) / rowH)
        : -1;

      for (let i = 0; i < corners.length; i++) {
        const c = corners[i];
        const y = PAD.top + i * rowH;
        const isHovered = i === hoveredIdx && hoveredIdx >= 0 && hoveredIdx < corners.length;

        // Corner name
        ctx.fillStyle = isHovered ? '#F3F0E8' : '#8A8F98';
        ctx.font = isHovered ? 'bold 9px "IBM Plex Mono", monospace' : '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(c.name, PAD.left - 5, y + rowH / 2);

        // Score bar background
        const score = Math.max(0, Math.min(1, c.score));
        const barW = score * plotW;
        const barColor = score >= 0.8 ? '#B6FF2E' : score >= 0.5 ? '#FFD400' : '#FF2A2A';

        ctx.fillStyle = isHovered ? 'rgba(138, 143, 152, 0.15)' : 'rgba(138, 143, 152, 0.08)';
        ctx.fillRect(PAD.left, y + 2, plotW, rowH - 4);
        ctx.fillStyle = isHovered ? barColor + 'CC' : barColor + '88';
        ctx.fillRect(PAD.left, y + 2, barW, rowH - 4);

        // Score percentage on bar
        ctx.font = '8px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left';
        ctx.fillStyle = '#F3F0E8';
        ctx.fillText(`${(score * 100).toFixed(0)}%`, PAD.left + barW + 5, y + rowH / 2);

        // Speed indicators on hover
        if (isHovered && plotW > 150) {
          ctx.font = '8px "IBM Plex Mono", monospace';
          ctx.textAlign = 'right';
          ctx.fillStyle = '#8A8F98';
          ctx.fillText(
            `E:${c.entry_speed.toFixed(0)} A:${c.apex_speed.toFixed(0)} X:${c.exit_speed.toFixed(0)}`,
            PAD.left + plotW,
            y + rowH / 2,
          );
        }
      }

      // Legend
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('E=Entry  A=Apex  X=Exit (km/h)', w / 2, h - 5);
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.corners.length === 0) return null;

      const idx = Math.floor(hover.ny * data.corners.length);
      if (idx < 0 || idx >= data.corners.length) return null;

      const c = data.corners[idx];
      const scoreColor = c.score >= 0.8 ? '#B6FF2E' : c.score >= 0.5 ? '#FFD400' : '#FF2A2A';
      return {
        header: c.name,
        lines: [
          { label: 'Score', value: `${(c.score * 100).toFixed(0)}%`, color: scoreColor },
          { label: 'Entry', value: `${c.entry_speed.toFixed(0)} km/h` },
          { label: 'Apex', value: `${c.apex_speed.toFixed(0)} km/h`, color: '#FFD400' },
          { label: 'Exit', value: `${c.exit_speed.toFixed(0)} km/h`, color: '#B6FF2E' },
        ],
      };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, cornerCount],
    padding: PAD,
    getTooltipData,
  });

  if (isLoading) return <ChartPanel title="Corner Mastery"><div className={`${height} flex items-center justify-center`}><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.corners.length === 0) return <ChartPanel title="Corner Mastery"><div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Corner Mastery" subtitle="Corner-by-corner performance">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
