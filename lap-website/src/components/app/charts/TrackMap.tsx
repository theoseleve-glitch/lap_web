'use client';

import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo, useEffect, useRef } from 'react';
import { api } from '@/lib/api-client';
import { ChartPanel } from '@/components/app';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

interface GpsTraceData {
  lat: number[];
  lon: number[];
  speed: number[];
}

interface Props {
  sessionId: string;
  height?: string;
  /** Callback fired when hover index changes (for cross-chart sync) */
  onHoverIndexChange?: (index: number | null) => void;
  /** External hover index set by another chart (for cross-chart sync) */
  externalHoverIndex?: number | null;
}

const PAD = { top: 15, right: 15, bottom: 20, left: 15 };

function lerpColor(t: number): string {
  const r = t < 0.5 ? 255 : Math.round(255 - (t - 0.5) * 2 * (255 - 182));
  const g = t < 0.5 ? Math.round(42 + t * 2 * (212 - 42)) : Math.round(212 + (t - 0.5) * 2 * (255 - 212));
  const b = t < 0.5 ? Math.round(42 - t * 2 * 42) : Math.round((t - 0.5) * 2 * 46);
  return `rgb(${r},${g},${b})`;
}

export function TrackMap({ sessionId, height = 'h-56', onHoverIndexChange, externalHoverIndex }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['session', sessionId, 'gps-trace'],
    queryFn: () => api.get<GpsTraceData>(`/sessions/${sessionId}/gps-trace`),
  });

  // Keep callback ref stable to avoid re-creating draw on every render
  const onHoverIndexChangeRef = useRef(onHoverIndexChange);
  onHoverIndexChangeRef.current = onHoverIndexChange;
  const externalHoverIndexRef = useRef(externalHoverIndex);
  externalHoverIndexRef.current = externalHoverIndex;

  const geo = useMemo(() => {
    if (!data || data.lat.length < 2) return null;
    const { lat, lon, speed } = data;
    const minLat = Math.min(...lat);
    const maxLat = Math.max(...lat);
    const minLon = Math.min(...lon);
    const maxLon = Math.max(...lon);
    const latRange = maxLat - minLat || 0.001;
    const lonRange = maxLon - minLon || 0.001;
    const minSpeed = Math.min(...speed);
    const maxSpeed = Math.max(...speed);
    const speedRange = maxSpeed - minSpeed || 1;
    return { minLat, maxLat, minLon, maxLon, latRange, lonRange, minSpeed, maxSpeed, speedRange };
  }, [data]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      if (!data || !geo || data.lat.length < 2) return;

      const { lat, lon, speed } = data;
      const { minLat, minLon, latRange, lonRange, minSpeed, speedRange } = geo;

      const plotW = w - PAD.left - PAD.right;
      const plotH = h - PAD.top - PAD.bottom;

      // Maintain aspect ratio
      const scaleX = plotW / lonRange;
      const scaleY = plotH / latRange;
      const scale = Math.min(scaleX, scaleY);
      const offsetX = PAD.left + (plotW - lonRange * scale) / 2;
      const offsetY = PAD.top + (plotH - latRange * scale) / 2;

      const toX = (lo: number) => offsetX + (lo - minLon) * scale;
      const toY = (la: number) => h - offsetY - (la - minLat) * scale;

      // Draw track segments colored by speed
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      for (let i = 1; i < lat.length; i++) {
        const t = (speed[i] - minSpeed) / speedRange;
        ctx.beginPath();
        ctx.strokeStyle = lerpColor(t);
        ctx.moveTo(toX(lon[i - 1]), toY(lat[i - 1]));
        ctx.lineTo(toX(lon[i]), toY(lat[i]));
        ctx.stroke();
      }

      // Start/finish marker
      ctx.beginPath();
      ctx.arc(toX(lon[0]), toY(lat[0]), 5, 0, Math.PI * 2);
      ctx.fillStyle = '#B6FF2E';
      ctx.fill();
      ctx.strokeStyle = '#161A20';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Resolve hover: local mouse hover takes priority, then external index
      let highlightIdx: number | null = null;

      if (hover) {
        // Find nearest point from local mouse position
        let bestDist = Infinity;
        let nearestIdx = -1;
        for (let i = 0; i < lat.length; i += 2) {
          const px = toX(lon[i]);
          const py = toY(lat[i]);
          const d = (hover.x - px) ** 2 + (hover.y - py) ** 2;
          if (d < bestDist) {
            bestDist = d;
            nearestIdx = i;
          }
        }
        if (nearestIdx >= 0 && bestDist < 900) {
          highlightIdx = nearestIdx;
          // Publish hover index to other charts
          if (onHoverIndexChangeRef.current) {
            onHoverIndexChangeRef.current(nearestIdx);
          }
        }
      } else if (externalHoverIndexRef.current != null) {
        // Use external hover index (from SpeedTrace)
        // The speed-trace data length may differ from GPS trace — clamp the index
        const extIdx = externalHoverIndexRef.current;
        if (extIdx >= 0 && extIdx < lat.length) {
          highlightIdx = extIdx;
        } else if (extIdx >= lat.length) {
          highlightIdx = lat.length - 1;
        }
      }

      // Draw highlight circle at the resolved index
      if (highlightIdx != null && highlightIdx >= 0 && highlightIdx < lat.length) {
        const px = toX(lon[highlightIdx]);
        const py = toY(lat[highlightIdx]);

        // Glow ring for external hover
        if (!hover && externalHoverIndexRef.current != null) {
          ctx.beginPath();
          ctx.arc(px, py, 10, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255, 212, 0, 0.15)';
          ctx.fill();
        }

        // Highlight circle
        ctx.beginPath();
        ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fillStyle = '#FFD400';
        ctx.fill();
        ctx.strokeStyle = '#161A20';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Speed legend gradient bar
      const gradW = Math.min(120, plotW * 0.3);
      const gradH = 6;
      const gradX = w - PAD.right - gradW;
      const gradY = h - 10;
      const grad = ctx.createLinearGradient(gradX, 0, gradX + gradW, 0);
      grad.addColorStop(0, lerpColor(0));
      grad.addColorStop(0.5, lerpColor(0.5));
      grad.addColorStop(1, lerpColor(1));
      ctx.fillStyle = grad;
      ctx.fillRect(gradX, gradY, gradW, gradH);

      ctx.fillStyle = '#8A8F98';
      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = 'left';
      ctx.fillText(`${geo.minSpeed.toFixed(0)}`, gradX, gradY - 2);
      ctx.textAlign = 'right';
      ctx.fillText(`${geo.maxSpeed.toFixed(0)} km/h`, gradX + gradW, gradY - 2);
    },
    [data, geo],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      if (!data || !geo || data.lat.length < 2) return null;

      // Find nearest point
      let minDist = Infinity;
      let nearestIdx = -1;
      const { lat, lon } = data;
      for (let i = 0; i < lat.length; i += 2) {
        const dx = hover.nx - ((lon[i] - geo.minLon) / geo.lonRange);
        const dy = hover.ny - (1 - (lat[i] - geo.minLat) / geo.latRange);
        const d = dx * dx + dy * dy;
        if (d < minDist) {
          minDist = d;
          nearestIdx = i;
        }
      }
      if (nearestIdx < 0 || minDist > 0.02) return null;

      const speed = data.speed[nearestIdx];
      const t = (speed - geo.minSpeed) / geo.speedRange;
      return {
        lines: [
          { label: 'Speed', value: `${speed.toFixed(1)} km/h`, color: lerpColor(t) },
          { label: 'Position', value: `${nearestIdx}/${data.lat.length}` },
        ],
      };
    },
    [data, geo],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [data, geo, externalHoverIndex],
    padding: PAD,
    getTooltipData,
  });

  // Clear hover when mouse leaves this chart
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !onHoverIndexChange) return;
    const handleLeave = () => onHoverIndexChange(null);
    canvas.addEventListener('mouseleave', handleLeave);
    return () => canvas.removeEventListener('mouseleave', handleLeave);
  }, [canvasRef, onHoverIndexChange]);

  if (isLoading)
    return (
      <ChartPanel title="Track Map">
        <div className={`${height} flex items-center justify-center`}>
          <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      </ChartPanel>
    );

  if (!data || data.lat.length === 0)
    return (
      <ChartPanel title="Track Map">
        <div className={`${height} flex items-center justify-center text-steel font-telemetry text-xs`}>
          No data available
        </div>
      </ChartPanel>
    );

  return (
    <ChartPanel title="Track Map" subtitle="GPS trace colored by speed">
      <div ref={containerRef} className="relative">
        <canvas ref={canvasRef} className={`w-full ${height}`} />
        <ChartTooltip tooltip={tooltip} />
      </div>
    </ChartPanel>
  );
}
