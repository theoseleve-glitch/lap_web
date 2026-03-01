'use client';

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface WeatherData {
  timestamps: number[];
  temperature: number[];
  humidity: number[];
  wind_speed: number[];
}

interface Props {
  sessionId: string;
}

const PAD = { top: 15, right: 45, bottom: 25, left: 45 };

export function WeatherChart({ sessionId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'weather'],
    queryFn: () => api.get<WeatherData>(`/sessions/${sessionId}/weather`),
  });

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || data.timestamps.length === 0) return;

      const { timestamps, temperature, humidity, wind_speed } = data;
      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      const minT = timestamps[0], maxT = timestamps[timestamps.length - 1];
      const tR = maxT - minT || 1;
      const cleanTemp = temperature.filter(Number.isFinite);
      const cleanWind = wind_speed.filter(Number.isFinite);
      const maxTemp = cleanTemp.length > 0 ? Math.max(...cleanTemp, 1) : 1;
      const minTemp = cleanTemp.length > 0 ? Math.min(...cleanTemp, 0) : 0;
      const tempR = maxTemp - minTemp || 1;
      const maxWind = cleanWind.length > 0 ? Math.max(...cleanWind, 1) : 1;

      const toX = (t: number) => { const v = PAD.left + ((t - minT) / tR) * plotW; return Number.isFinite(v) ? v : PAD.left; };

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

      // Left Y-axis labels (temp)
      ctx.fillStyle = '#FF6A00';
      ctx.font = '10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {
        ctx.fillText(`${(maxTemp - (i / 4) * tempR).toFixed(0)}C`, PAD.left - 5, PAD.top + (i / 4) * plotH + 3);
      }

      const safeY = (raw: number, min: number, range: number) => {
        const v = Number.isFinite(raw) ? raw : min;
        const y = PAD.top + plotH - ((v - min) / range) * plotH;
        return Number.isFinite(y) ? y : PAD.top;
      };
      const safeYRatio = (raw: number, maxVal: number) => {
        const v = Number.isFinite(raw) ? raw : 0;
        const y = PAD.top + plotH - (v / Math.max(maxVal, 0.001)) * plotH;
        return Number.isFinite(y) ? y : PAD.top;
      };

      // Temperature line
      ctx.beginPath();
      ctx.strokeStyle = '#FF6A00';
      ctx.lineWidth = 2;
      for (let i = 0; i < timestamps.length; i++) {
        const x = toX(timestamps[i]);
        const y = safeY(temperature[i], minTemp, tempR);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Humidity (0-100%)
      ctx.beginPath();
      ctx.strokeStyle = '#B6FF2E88';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      for (let i = 0; i < timestamps.length; i++) {
        const x = toX(timestamps[i]);
        const y = safeYRatio(humidity[i], 100);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Wind speed
      ctx.beginPath();
      ctx.strokeStyle = '#FFD400';
      ctx.lineWidth = 1;
      for (let i = 0; i < timestamps.length; i++) {
        const x = toX(timestamps[i]);
        const y = safeYRatio(wind_speed[i], maxWind);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      // Hover dots
      if (hover) {
        const hoverTS = minT + hover.nx * tR;
        let idx = 0, diff = Infinity;
        for (let i = 0; i < timestamps.length; i++) {
          const d = Math.abs(timestamps[i] - hoverTS);
          if (d < diff) { diff = d; idx = i; }
        }
        const x = toX(timestamps[idx]);
        // Temp dot
        ctx.beginPath();
        ctx.arc(x, safeY(temperature[idx], minTemp, tempR), 4, 0, Math.PI * 2);
        ctx.fillStyle = '#FF6A00';
        ctx.fill();
        ctx.strokeStyle = '#F3F0E8';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        // Humidity dot
        ctx.beginPath();
        ctx.arc(x, safeYRatio(humidity[idx], 100), 3, 0, Math.PI * 2);
        ctx.fillStyle = '#B6FF2E';
        ctx.fill();
        // Wind dot
        ctx.beginPath();
        ctx.arc(x, safeYRatio(wind_speed[idx], maxWind), 3, 0, Math.PI * 2);
        ctx.fillStyle = '#FFD400';
        ctx.fill();
      }

      // Legend
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      let lx = PAD.left + 5;
      const items: [string, string][] = [['#FF6A00', 'Temp'], ['#B6FF2E', 'Humid'], ['#FFD400', 'Wind']];
      for (const [color, label] of items) {
        ctx.fillStyle = color;
        ctx.fillRect(lx, PAD.top + 2, 10, 3);
        ctx.fillStyle = '#8A8F98';
        ctx.fillText(label, lx + 14, PAD.top + 6);
        lx += 55;
      }
    },
    [data],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || data.timestamps.length === 0) return null;
      const { timestamps, temperature, humidity, wind_speed } = data;
      const hoverTS = timestamps[0] + hover.nx * (timestamps[timestamps.length - 1] - timestamps[0] || 1);
      let idx = 0, diff = Infinity;
      for (let i = 0; i < timestamps.length; i++) {
        const d = Math.abs(timestamps[i] - hoverTS);
        if (d < diff) { diff = d; idx = i; }
      }
      return {
        header: `${timestamps[idx].toFixed(1)}s`,
        lines: [
          { label: 'Temp', value: `${temperature[idx].toFixed(1)}°C`, color: '#FF6A00' },
          { label: 'Humidity', value: `${humidity[idx].toFixed(0)}%`, color: '#B6FF2E' },
          { label: 'Wind', value: `${wind_speed[idx].toFixed(1)} m/s`, color: '#FFD400' },
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
    crosshairColor: 'rgba(255, 106, 0, 0.3)',
  });

  return (
    <ChartPanel title="Weather Conditions" subtitle="Temperature, humidity, wind" loading={isLoading}>
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className="w-full h-48" />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
