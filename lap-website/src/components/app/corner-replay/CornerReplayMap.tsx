'use client';

import { useRef, useEffect, useCallback } from 'react';

/** Design-token hex colors */
const COLORS = {
  asphalt: '#0B0C0F',
  concrete: '#161A20',
  chalk: '#F3F0E8',
  steel: '#8A8F98',
  acidGreen: '#B6FF2E',
  pitOrange: '#FF6A00',
  safetyRed: '#FF2A2A',
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

function drawMap(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  gpsPath: GpsPoint[],
  currentFrame: number,
  totalFrames: number,
) {
  ctx.clearRect(0, 0, w, h);

  // Background
  ctx.fillStyle = COLORS.concrete;
  ctx.fillRect(0, 0, w, h);

  if (gpsPath.length < 2) {
    ctx.fillStyle = COLORS.steel;
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No GPS data', w / 2, h / 2);
    return;
  }

  const pad = 24;
  const plotW = w - pad * 2;
  const plotH = h - pad * 2;

  // Compute bounds
  const lats = gpsPath.map((p) => p.lat);
  const lons = gpsPath.map((p) => p.lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const latRange = maxLat - minLat || 0.0001;
  const lonRange = maxLon - minLon || 0.0001;

  // Maintain aspect ratio
  const scaleX = plotW / lonRange;
  const scaleY = plotH / latRange;
  const scale = Math.min(scaleX, scaleY);
  const offsetX = pad + (plotW - lonRange * scale) / 2;
  const offsetY = pad + (plotH - latRange * scale) / 2;

  const toX = (lon: number) => offsetX + (lon - minLon) * scale;
  const toY = (lat: number) => h - offsetY - (lat - minLat) * scale;

  // Grid lines (subtle)
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

  // Draw full path in muted steel
  ctx.beginPath();
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.25)';
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  for (let i = 0; i < gpsPath.length; i++) {
    const x = toX(gpsPath[i].lon);
    const y = toY(gpsPath[i].lat);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Draw traversed path in acid-green
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
      const x = toX(gpsPath[i].lon);
      const y = toY(gpsPath[i].lat);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Current position dot (pit-orange)
  const curPoint = gpsPath[frameIdx];
  const cx = toX(curPoint.lon);
  const cy = toY(curPoint.lat);

  // Glow effect
  const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, 12);
  glow.addColorStop(0, COLORS.pitOrange + '66');
  glow.addColorStop(1, COLORS.pitOrange + '00');
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(cx, cy, 12, 0, Math.PI * 2);
  ctx.fill();

  // Solid dot
  ctx.beginPath();
  ctx.arc(cx, cy, 5, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.pitOrange;
  ctx.fill();
  ctx.strokeStyle = COLORS.chalk;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Start marker
  const sx = toX(gpsPath[0].lon);
  const sy = toY(gpsPath[0].lat);
  ctx.beginPath();
  ctx.arc(sx, sy, 4, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.acidGreen;
  ctx.fill();

  // Scale indicator
  const scaleBarLen = 50;
  const metersPerPx = latRange * 111_320 / (latRange * scale);
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
}

export function CornerReplayMap({ gpsPath, currentFrame, totalFrames }: CornerReplayMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    drawMap(ctx, rect.width, rect.height, gpsPath, currentFrame, totalFrames);
  }, [gpsPath, currentFrame, totalFrames]);

  useEffect(() => {
    render();
  }, [render]);

  // Resize observer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => render());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [render]);

  return (
    <div className="relative w-full h-full min-h-[200px] bg-concrete rounded-lg border border-steel/20 overflow-hidden">
      <div className="absolute top-3 left-3 z-10">
        <span className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
          Track Map
        </span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full" />
    </div>
  );
}
