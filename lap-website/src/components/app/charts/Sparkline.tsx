'use client';

import { useRef, useEffect } from 'react';

interface SparklineProps {
  data: number[];
  color?: string;
  height?: number;
  className?: string;
}

export function Sparkline({
  data,
  color = '#B6FF2E',
  height = 40,
  className = '',
}: SparklineProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const padding = 2;
    const plotW = w - padding * 2;
    const plotH = h - padding * 2;

    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;

    ctx.clearRect(0, 0, w, h);

    // Draw line
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';

    for (let i = 0; i < data.length; i++) {
      const x = padding + (i / (data.length - 1)) * plotW;
      const y = padding + plotH - ((data[i] - min) / range) * plotH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Draw fill gradient
    ctx.lineTo(padding + plotW, padding + plotH);
    ctx.lineTo(padding, padding + plotH);
    ctx.closePath();

    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, color + '33');
    grad.addColorStop(1, color + '05');
    ctx.fillStyle = grad;
    ctx.fill();
  }, [data, color]);

  if (data.length === 0) return null;

  return (
    <canvas
      ref={canvasRef}
      className={`w-full ${className}`}
      style={{ height }}
    />
  );
}
