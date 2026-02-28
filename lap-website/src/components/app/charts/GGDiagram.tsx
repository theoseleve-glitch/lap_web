'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface GGData {
  lat_g: number[];
  lon_g: number[];
}

interface Props {
  sessionId: string;
  height?: string;
}

const PAD = { top: 15, right: 15, bottom: 28, left: 45 };

export function GGDiagram({ sessionId, height = 'h-56' }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'gg-data'],
    queryFn: () => api.get<GGData>(`/sessions/${sessionId}/gg-data`),
  });

  const stats = useMemo(() => {
    if (!data || data.lat_g.length === 0) return null;
    const maxAbsLat = Math.max(...data.lat_g.map(Math.abs), 0.5);
    const maxAbsLon = Math.max(...data.lon_g.map(Math.abs), 0.5);
    const maxG = Math.max(maxAbsLat, maxAbsLon);
    return { maxG, maxAbsLat, maxAbsLon };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !stats || data.lat_g.length === 0) return;

      const { lat_g, lon_g } = data;
      const { maxG } = stats;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;
      const cx = PAD.left + plotW / 2;
      const cy = PAD.top + plotH / 2;
      const halfR = Math.min(plotW, plotH) / 2;

      // Circle guides
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.12)';
      ctx.lineWidth = 0.5;
      const nRings = Math.ceil(maxG / 0.5);
      for (let i = 1; i <= nRings; i++) {
        const r = (i * 0.5 / maxG) * halfR;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();

        // Ring label
        ctx.fillStyle = '#8A8F9860';
        ctx.font = '8px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`${(i * 0.5).toFixed(1)}G`, cx + r + 2, cy - 3);
      }

      // Crosshair axes
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.25)';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(PAD.left, cy);
      ctx.lineTo(PAD.left + plotW, cy);
      ctx.moveTo(cx, PAD.top);
      ctx.lineTo(cx, PAD.top + plotH);
      ctx.stroke();

      // Axis labels
      ctx.fillStyle = '#8A8F98';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Lateral G', cx, h - 5);
      ctx.save();
      ctx.translate(12, cy);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText('Lon G', 0, 0);
      ctx.restore();

      // Scatter points
      for (let i = 0; i < lat_g.length; i++) {
        const x = cx + (lat_g[i] / maxG) * halfR;
        const y = cy - (lon_g[i] / maxG) * halfR;
        ctx.beginPath();
        ctx.arc(x, y, 1.5, 0, Math.PI * 2);
        ctx.fillStyle = lon_g[i] > 0 ? '#B6FF2E66' : '#FF2A2A66';
        ctx.fill();
      }

      // Hover: find nearest point and highlight
      if (hover) {
        let minDist = Infinity;
        let nearestIdx = -1;
        for (let i = 0; i < lat_g.length; i++) {
          const px = cx + (lat_g[i] / maxG) * halfR;
          const py = cy - (lon_g[i] / maxG) * halfR;
          const d = (hover.x - px) ** 2 + (hover.y - py) ** 2;
          if (d < minDist) {
            minDist = d;
            nearestIdx = i;
          }
        }
        if (nearestIdx >= 0 && minDist < 400) {
          const px = cx + (lat_g[nearestIdx] / maxG) * halfR;
          const py = cy - (lon_g[nearestIdx] / maxG) * halfR;
          ctx.beginPath();
          ctx.arc(px, py, 5, 0, Math.PI * 2);
          ctx.fillStyle = lon_g[nearestIdx] > 0 ? '#B6FF2E' : '#FF2A2A';
          ctx.fill();
          ctx.strokeStyle = '#161A20';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      // Stats overlay (top-right corner)
      ctx.fillStyle = '#8A8F98';
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`Max Lat: ${stats.maxAbsLat.toFixed(2)}G`, w - PAD.right, PAD.top + 10);
      ctx.fillText(`Max Lon: ${stats.maxAbsLon.toFixed(2)}G`, w - PAD.right, PAD.top + 22);
    },
    [data, stats],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || !stats || data.lat_g.length === 0) return null;

      const { lat_g, lon_g } = data;
      const { maxG } = stats;
      // Find nearest point
      let minDist = Infinity;
      let nearestIdx = -1;
      // We need canvas dimensions — approximate from hover coordinates
      for (let i = 0; i < lat_g.length; i += 3) { // sample every 3rd point for performance
        const dist = Math.abs(hover.nx - 0.5 - (lat_g[i] / maxG) * 0.5) ** 2 +
                     Math.abs(hover.ny - 0.5 + (lon_g[i] / maxG) * 0.5) ** 2;
        if (dist < minDist) {
          minDist = dist;
          nearestIdx = i;
        }
      }
      if (nearestIdx < 0 || minDist > 0.05) return null;

      return {
        header: lon_g[nearestIdx] > 0 ? 'Acceleration' : 'Braking',
        lines: [
          { label: 'Lat G', value: `${lat_g[nearestIdx].toFixed(3)}`, color: '#B6FF2E' },
          { label: 'Lon G', value: `${lon_g[nearestIdx].toFixed(3)}`, color: lon_g[nearestIdx] > 0 ? '#B6FF2E' : '#FF2A2A' },
          { label: 'Total', value: `${Math.sqrt(lat_g[nearestIdx] ** 2 + lon_g[nearestIdx] ** 2).toFixed(3)}G` },
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

  if (isLoading)
    return (
      <ChartPanel title="GG Diagram">
        <div className={`${height} flex items-center justify-center`}>
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </ChartPanel>
    );

  if (!data || data.lat_g.length === 0)
    return (
      <ChartPanel title="GG Diagram">
        <div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>
          No data available
        </div>
      </ChartPanel>
    );

  return (
    <ChartPanel title="GG Diagram" subtitle="Lateral vs longitudinal G-force">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
