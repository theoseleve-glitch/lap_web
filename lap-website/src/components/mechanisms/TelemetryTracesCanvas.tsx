'use client';

import { useRef, useEffect, useCallback } from 'react';
import { colors } from '@/lib/tokens';

interface TelemetryTracesCanvasProps {
  progress?: number;
  hoveredTrace?: string | null;
  className?: string;
}

// Generate smooth trace data
function generateSpeedTrace(steps: number): number[] {
  return Array.from({ length: steps }, (_, i) => {
    const t = i / steps;
    return 0.5 + 0.35 * Math.sin(t * Math.PI * 4) + 0.1 * Math.sin(t * Math.PI * 7);
  });
}

function generateBrakeTrace(steps: number): number[] {
  return Array.from({ length: steps }, (_, i) => {
    const t = i / steps;
    const spike1 = Math.max(0, 1 - Math.abs(t - 0.2) * 8);
    const spike2 = Math.max(0, 1 - Math.abs(t - 0.5) * 10);
    const spike3 = Math.max(0, 1 - Math.abs(t - 0.8) * 7);
    return 0.1 + 0.8 * Math.max(spike1, spike2, spike3);
  });
}

function generateSteeringTrace(steps: number): number[] {
  return Array.from({ length: steps }, (_, i) => {
    const t = i / steps;
    return 0.5 + 0.3 * Math.sin(t * Math.PI * 6) + 0.15 * Math.cos(t * Math.PI * 3);
  });
}

const TRACES = [
  { name: 'speed', color: colors.chalk, data: generateSpeedTrace(200), width: 3 },
  { name: 'brake', color: colors.safetyRed, data: generateBrakeTrace(200), width: 2.5 },
  { name: 'steering', color: colors.steel, data: generateSteeringTrace(200), width: 2 },
];

export function TelemetryTracesCanvas({
  progress = 1,
  hoveredTrace = null,
  className = '',
}: TelemetryTracesCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    const drawCount = Math.floor(progress * 200);
    const padding = 40;
    const usableHeight = height - padding * 2;

    TRACES.forEach((trace) => {
      const isHovered = hoveredTrace === trace.name;
      const isDimmed = hoveredTrace !== null && !isHovered;

      ctx.save();
      ctx.globalAlpha = isDimmed ? 0.1 : isHovered ? 1 : 0.7;
      ctx.strokeStyle = trace.color;
      ctx.lineWidth = isHovered ? trace.width * 1.5 : trace.width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();

      for (let i = 0; i < drawCount; i++) {
        const x = (i / 200) * width;
        const y = padding + (1 - trace.data[i]) * usableHeight;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }

      ctx.stroke();
      ctx.restore();
    });
  }, [progress, hoveredTrace]);

  useEffect(() => {
    render();
    window.addEventListener('resize', render);
    return () => window.removeEventListener('resize', render);
  }, [render]);

  return (
    <canvas
      ref={canvasRef}
      className={`w-full h-64 md:h-80 ${className}`}
      aria-label="Telemetry traces visualization — speed, brake, and steering data"
      role="img"
    />
  );
}
