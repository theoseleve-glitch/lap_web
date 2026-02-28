'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface SectorData {
  sectors: { name: string; best: number; avg: number; worst: number }[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 22, right: 15, bottom: 28, left: 50 };
const COLORS = { best: '#B6FF2E', avg: '#FFD400', worst: '#FF2A2A' };

export function SectorChart({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'sectors'],
    queryFn: () => api.get<SectorData>(`/sessions/${sessionId}/sectors`),
  });

  const maxTime = useMemo(() => {
    if (!data || data.sectors.length === 0) return 0;
    return Math.max(...data.sectors.flatMap((s) => [s.best, s.avg, s.worst]));
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.sectors.length === 0) return;

      const { sectors } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const groupW = plotW / sectors.length;
      const barW = Math.min(14, groupW / 4);

      // Grid + Y-axis
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = PAD.top + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + plotW, y);
        ctx.stroke();

        ctx.fillStyle = '#8A8F98';
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'right';
        const val = maxTime - (i / 4) * maxTime;
        ctx.fillText(`${val.toFixed(1)}s`, PAD.left - 6, y + 3);
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      let lx = PAD.left;
      for (const [label, color] of Object.entries(COLORS)) {
        ctx.fillStyle = color;
        ctx.fillRect(lx, PAD.top - 16, 8, 8);
        ctx.fillStyle = '#8A8F98';
        ctx.fillText(label, lx + 11, PAD.top - 9);
        lx += 52;
      }

      // Hovered sector index
      const hoveredSector = hover ? Math.floor(hover.nx * sectors.length) : -1;

      // Bars
      for (let i = 0; i < sectors.length; i++) {
        const s = sectors[i];
        const cx = PAD.left + i * groupW + groupW / 2;
        const isHovered = i === hoveredSector;

        const vals = [
          { v: s.best, c: COLORS.best },
          { v: s.avg, c: COLORS.avg },
          { v: s.worst, c: COLORS.worst },
        ];

        for (let j = 0; j < vals.length; j++) {
          const barH = (vals[j].v / maxTime) * plotH;
          const x = cx + (j - 1) * (barW + 2) - barW / 2;
          ctx.fillStyle = isHovered ? vals[j].c : vals[j].c + 'AA';
          ctx.fillRect(x, PAD.top + plotH - barH, barW, barH);
        }

        // Sector label
        ctx.fillStyle = isHovered ? '#F3F0E8' : '#8A8F98';
        ctx.font = isHovered ? 'bold 10px "IBM Plex Mono", monospace' : '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(s.name, cx, h - 6);
      }
    },
    [data, maxTime],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.sectors.length === 0) return null;
      const idx = Math.floor(hover.nx * data.sectors.length);
      if (idx < 0 || idx >= data.sectors.length) return null;

      const s = data.sectors[idx];
      return {
        header: s.name,
        lines: [
          { label: 'Best', value: `${s.best.toFixed(3)}s`, color: COLORS.best },
          { label: 'Avg', value: `${s.avg.toFixed(3)}s`, color: COLORS.avg },
          { label: 'Worst', value: `${s.worst.toFixed(3)}s`, color: COLORS.worst },
          { label: 'Spread', value: `${(s.worst - s.best).toFixed(3)}s` },
        ],
      };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, maxTime],
    padding: PAD,
    getTooltipData,
  });

  if (isLoading)
    return (
      <ChartPanel title="Sector Times">
        <div className={`${height} flex items-center justify-center`}>
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </ChartPanel>
    );

  if (!data || data.sectors.length === 0)
    return (
      <ChartPanel title="Sector Times">
        <div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>
          No data available
        </div>
      </ChartPanel>
    );

  return (
    <ChartPanel title="Sector Times" subtitle="Best / avg / worst comparison">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
