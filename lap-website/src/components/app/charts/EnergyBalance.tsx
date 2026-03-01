'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface EnergyData {
  distances: number[];
  kinetic_energy: number[];
  braking_energy: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 10, right: 15, bottom: 30, left: 50 };

export function EnergyBalance({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'energy'],
    queryFn: () => api.get<EnergyData>(`/sessions/${sessionId}/energy`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.distances.length === 0) return;

      const { distances, kinetic_energy, braking_energy } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const minDist = distances[0], maxDist = distances[distances.length - 1];
      const dR = maxDist - minDist || 1;
      const allE = [...kinetic_energy, ...braking_energy].filter(Number.isFinite);
      const maxE = allE.length > 0 ? Math.max(...allE, 0.001) : 0.001;
      const minE = allE.length > 0 ? Math.min(...allE, 0) : 0;
      const eR = maxE - minE || 1;

      const toX = (d: number) => { const v = PAD.left + ((d - minDist) / dR) * plotW; return Number.isFinite(v) ? v : PAD.left; };
      const toY = (e: number) => { const v = PAD.top + plotH - ((e - minE) / eR) * plotH; return Number.isFinite(v) ? v : PAD.top; };

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
        ctx.fillText(`${((maxE - (i / 4) * eR) / 1000).toFixed(1)}kJ`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }

      // KE line
      ctx.beginPath();
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 1.5;
      for (let i = 0; i < distances.length; i++) {
        const x = toX(distances[i]), y = toY(kinetic_energy[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Braking energy line
      ctx.beginPath();
      ctx.strokeStyle = '#FF2A2A';
      ctx.lineWidth = 1.5;
      for (let i = 0; i < distances.length; i++) {
        const x = toX(distances[i]), y = toY(braking_energy[i]);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Hover dots
      if (hover) {
        const hoverDist = minDist + hover.nx * dR;
        let idx = 0, diff = Infinity;
        for (let i = 0; i < distances.length; i++) {
          const d = Math.abs(distances[i] - hoverDist);
          if (d < diff) { diff = d; idx = i; }
        }
        // KE dot
        ctx.beginPath();
        ctx.arc(toX(distances[idx]), toY(kinetic_energy[idx]), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        // Braking dot
        ctx.beginPath();
        ctx.arc(toX(distances[idx]), toY(braking_energy[idx]), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#FF2A2A';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillStyle = '#B6FF2E';
      ctx.fillRect(PAD.left + 5, PAD.top + 5, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Kinetic', PAD.left + 20, PAD.top + 9);
      ctx.fillStyle = '#FF2A2A';
      ctx.fillRect(PAD.left + 75, PAD.top + 5, 10, 3);
      ctx.fillStyle = '#8A8F98';
      ctx.fillText('Braking', PAD.left + 90, PAD.top + 9);
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.distances.length === 0) return null;
      const { distances, kinetic_energy, braking_energy } = data;
      const hoverDist = distances[0] + hover.nx * (distances[distances.length - 1] - distances[0] || 1);
      let idx = 0, diff = Infinity;
      for (let i = 0; i < distances.length; i++) {
        const d = Math.abs(distances[i] - hoverDist);
        if (d < diff) { diff = d; idx = i; }
      }
      return {
        header: `${distances[idx].toFixed(0)} m`,
        lines: [
          { label: 'Kinetic', value: `${(kinetic_energy[idx] / 1000).toFixed(2)} kJ`, color: '#B6FF2E' },
          { label: 'Braking', value: `${(braking_energy[idx] / 1000).toFixed(2)} kJ`, color: '#FF2A2A' },
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
    <ChartPanel title="Energy Balance" subtitle="Kinetic energy management" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
