'use client';

import { useCallback, useRef } from 'react';
import { ChartTooltip } from '@/components/app/ChartTooltip';
import { useInteractiveCanvas, type HoverPoint, type TooltipData } from '@/hooks/useInteractiveCanvas';

const COLORS = {
  concrete: '#161A20',
  chalk: '#F3F0E8',
  steel: '#8A8F98',
  acidGreen: '#B6FF2E',
  pitOrange: '#FF6A00',
  marshalYellow: '#FFD400',
};

interface GpsPoint {
  lat: number;
  lon: number;
}

interface CornerReplayMapProps {
  gpsPath: GpsPoint[];
  currentFrame: number;
  totalFrames: number;
}

const PAD = { top: 24, right: 24, bottom: 24, left: 24 };

interface MapScreenPoint {
  x: number;
  y: number;
  lat: number;
  lon: number;
  frac: number;
}

export function CornerReplayMap({ gpsPath, currentFrame, totalFrames }: CornerReplayMapProps) {
  const pathRef = useRef<MapScreenPoint[]>([]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = COLORS.concrete;
      ctx.fillRect(0, 0, w, h);

      if (gpsPath.length < 2) {
        ctx.fillStyle = COLORS.steel;
        ctx.font = '12px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('No GPS data', w / 2, h / 2);
        pathRef.current = [];
        return;
      }

      const pad = 24;
      const plotW = w - pad * 2;
      const plotH = h - pad * 2;

      const lats = gpsPath.map((p) => p.lat);
      const lons = gpsPath.map((p) => p.lon);
      const minLat = Math.min(...lats);
      const maxLat = Math.max(...lats);
      const minLon = Math.min(...lons);
      const maxLon = Math.max(...lons);
      const latRange = maxLat - minLat || 0.0001;
      const lonRange = maxLon - minLon || 0.0001;

      const scaleX = plotW / lonRange;
      const scaleY = plotH / latRange;
      const scale = Math.min(scaleX, scaleY);
      const offsetX = pad + (plotW - lonRange * scale) / 2;
      const offsetY = pad + (plotH - latRange * scale) / 2;

      const toX = (lon: number) => offsetX + (lon - minLon) * scale;
      const toY = (lat: number) => h - offsetY - (lat - minLat) * scale;

      // Store screen points for ref-bridge
      const screenPts: MapScreenPoint[] = gpsPath.map((p, i) => ({
        x: toX(p.lon),
        y: toY(p.lat),
        lat: p.lat,
        lon: p.lon,
        frac: i / (gpsPath.length - 1),
      }));
      pathRef.current = screenPts;

      // Grid
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.08)';
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= 4; i++) {
        const y = pad + (i / 4) * plotH;
        ctx.beginPath();
        ctx.moveTo(pad, y);
        ctx.lineTo(w - pad, y);
        ctx.stroke();
        const x = pad + (i / 4) * plotW;
        ctx.beginPath();
        ctx.moveTo(x, pad);
        ctx.lineTo(x, h - pad);
        ctx.stroke();
      }

      // Full path (muted)
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(138, 143, 152, 0.25)';
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      for (let i = 0; i < gpsPath.length; i++) {
        if (i === 0) ctx.moveTo(screenPts[i].x, screenPts[i].y);
        else ctx.lineTo(screenPts[i].x, screenPts[i].y);
      }
      ctx.stroke();

      // Traversed path (acid-green)
      const frameIdx = Math.min(
        Math.max(0, Math.round((currentFrame / Math.max(totalFrames - 1, 1)) * (gpsPath.length - 1))),
        gpsPath.length - 1,
      );
      if (frameIdx > 0) {
        ctx.beginPath();
        ctx.strokeStyle = COLORS.acidGreen;
        ctx.lineWidth = 2.5;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        for (let i = 0; i <= frameIdx; i++) {
          if (i === 0) ctx.moveTo(screenPts[i].x, screenPts[i].y);
          else ctx.lineTo(screenPts[i].x, screenPts[i].y);
        }
        ctx.stroke();
      }

      // Current position dot
      const cx = screenPts[frameIdx].x;
      const cy = screenPts[frameIdx].y;

      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, 12);
      glow.addColorStop(0, COLORS.pitOrange + '66');
      glow.addColorStop(1, COLORS.pitOrange + '00');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, 12, 0, Math.PI * 2);
      ctx.fill();

      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.pitOrange;
      ctx.fill();
      ctx.strokeStyle = COLORS.chalk;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Start marker
      ctx.beginPath();
      ctx.arc(screenPts[0].x, screenPts[0].y, 4, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.acidGreen;
      ctx.fill();

      // Hover point highlight
      if (hover) {
        let nearest = -1, bestDist = Infinity;
        for (let i = 0; i < screenPts.length; i++) {
          const d = (screenPts[i].x - hover.x) ** 2 + (screenPts[i].y - hover.y) ** 2;
          if (d < bestDist) { bestDist = d; nearest = i; }
        }
        if (nearest >= 0 && bestDist < 625) { // 25px radius
          const pt = screenPts[nearest];
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, 6, 0, Math.PI * 2);
          ctx.fillStyle = COLORS.marshalYellow;
          ctx.fill();
          ctx.strokeStyle = COLORS.chalk;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      // Scale indicator
      const scaleBarLen = 50;
      const metersPerPx = (latRange * 111_320) / (latRange * scale);
      const scaleMeters = Math.round(scaleBarLen * metersPerPx);
      ctx.strokeStyle = COLORS.steel;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(w - pad - scaleBarLen, h - 10);
      ctx.lineTo(w - pad, h - 10);
      ctx.stroke();
      ctx.fillStyle = COLORS.steel;
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText(`~${scaleMeters}m`, w - pad - scaleBarLen / 2, h - 14);
    },
    [gpsPath, currentFrame, totalFrames],
  );

  const getTooltipData = useCallback(
    (hover: HoverPoint): TooltipData | null => {
      const pts = pathRef.current;
      if (pts.length === 0) return null;
      let nearest = -1, bestDist = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const d = (pts[i].x - hover.x) ** 2 + (pts[i].y - hover.y) ** 2;
        if (d < bestDist) { bestDist = d; nearest = i; }
      }
      if (nearest < 0 || bestDist > 625) return null;
      const pt = pts[nearest];
      return {
        header: `Point ${nearest + 1} / ${pts.length}`,
        lines: [
          { label: 'Lat', value: pt.lat.toFixed(6), color: '#F3F0E8' },
          { label: 'Lon', value: pt.lon.toFixed(6), color: '#F3F0E8' },
          { label: 'Progress', value: `${(pt.frac * 100).toFixed(0)}%`, color: COLORS.acidGreen },
        ],
      };
    },
    [gpsPath],
  );

  const { canvasRef, containerRef, tooltip } = useInteractiveCanvas({
    draw,
    deps: [gpsPath, currentFrame, totalFrames],
    padding: PAD,
    getTooltipData,
  });

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full min-h-[200px] bg-concrete rounded-lg border border-steel/20 overflow-hidden"
    >
      <div className="absolute top-3 left-3 z-10 pointer-events-none">
        <span className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
          Track Map
        </span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full" />
      <ChartTooltip tooltip={tooltip} />
    </div>
  );
}
