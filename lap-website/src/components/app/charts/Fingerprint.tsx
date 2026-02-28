'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface FingerprintData {
  metrics: { name: string; value: number; max: number }[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 10, right: 15, bottom: 10, left: 100 };

export function Fingerprint({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'fingerprint'],
    queryFn: () => api.get<FingerprintData>(`/sessions/${sessionId}/fingerprint`),
  });

  const metricCount = useMemo(() => data?.metrics.length ?? 0, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.metrics.length === 0) return;

      const { metrics } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const rowH = plotH / metrics.length;

      const hoveredIdx = hover
        ? Math.floor((hover.y - PAD.top) / rowH)
        : -1;

      for (let i = 0; i < metrics.length; i++) {
        const y = PAD.top + i * rowH;
        const pct = metrics[i].max > 0 ? metrics[i].value / metrics[i].max : 0;
        const barW = Math.max(0, pct * plotW);
        const isHovered = i === hoveredIdx && hoveredIdx >= 0 && hoveredIdx < metrics.length;

        // Label
        ctx.fillStyle = isHovered ? '#F3F0E8' : '#8A8F98';
        ctx.font = isHovered ? 'bold 10px "IBM Plex Mono", monospace' : '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(metrics[i].name, PAD.left - 8, y + rowH / 2);

        // Background bar
        ctx.fillStyle = isHovered ? 'rgba(138, 143, 152, 0.18)' : 'rgba(138, 143, 152, 0.1)';
        ctx.fillRect(PAD.left, y + 4, plotW, rowH - 8);

        // Value bar
        const hue = pct > 0.7 ? '#B6FF2E' : pct > 0.4 ? '#FFD400' : '#FF6A00';
        ctx.fillStyle = isHovered ? hue : hue + 'CC';
        ctx.fillRect(PAD.left, y + 4, barW, rowH - 8);

        // Value text
        ctx.fillStyle = '#F3F0E8';
        ctx.font = '9px "IBM Plex Mono", monospace';
        ctx.textAlign = 'left';
        ctx.fillText(
          `${metrics[i].value.toFixed(1)}/${metrics[i].max}`,
          PAD.left + barW + 5,
          y + rowH / 2,
        );
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.metrics.length === 0) return null;

      const idx = Math.floor(hover.ny * data.metrics.length);
      if (idx < 0 || idx >= data.metrics.length) return null;

      const m = data.metrics[idx];
      const pct = m.max > 0 ? (m.value / m.max) * 100 : 0;
      const tier = pct >= 80 ? 'Excellent' : pct >= 60 ? 'Good' : pct >= 40 ? 'Average' : 'Needs Work';
      const color = pct >= 80 ? '#B6FF2E' : pct >= 60 ? '#FFD400' : '#FF6A00';
      return {
        header: m.name,
        lines: [
          { label: 'Score', value: `${m.value.toFixed(1)}/${m.max}`, color },
          { label: 'Level', value: `${pct.toFixed(0)}% — ${tier}` },
        ],
      };
    },
    [data],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, metricCount],
    padding: PAD,
    getTooltipData,
  });

  if (isLoading) return <ChartPanel title="Driver Fingerprint"><div className={`${height} flex items-center justify-center`}><div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" /></div></ChartPanel>;
  if (!data || data.metrics.length === 0) return <ChartPanel title="Driver Fingerprint"><div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>No data available</div></ChartPanel>;

  return (
    <ChartPanel title="Driver Fingerprint" subtitle="Unique driving signature">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
