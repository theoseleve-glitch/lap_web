'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { computeCornerDelta, type ControlPoint } from '@/lib/corner-physics';
import { colors } from '@/lib/tokens';

interface CornerDragProps {
  onDeltaChange: (delta: number) => void;
  className?: string;
}

const CANVAS_SIZE = 400;
const POINT_RADIUS = 14;

const OPTIMAL: ControlPoint[] = [
  { x: 0.15, y: 0.9 },
  { x: 0.55, y: 0.45 },
  { x: 0.95, y: 0.15 },
];

const INITIAL: ControlPoint[] = [
  { x: 0.2, y: 0.85 },
  { x: 0.65, y: 0.55 },
  { x: 0.9, y: 0.2 },
];

const LABELS = ['ENTRY', 'APEX', 'EXIT'];

function drawBezier(
  ctx: CanvasRenderingContext2D,
  points: ControlPoint[],
  size: number,
  color: string,
  width: number,
  alpha = 1,
) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = 'round';
  ctx.beginPath();

  const [p0, p1, p2] = points;
  ctx.moveTo(p0.x * size, p0.y * size);

  const steps = 40;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const x = (1 - t) ** 2 * p0.x + 2 * (1 - t) * t * p1.x + t ** 2 * p2.x;
    const y = (1 - t) ** 2 * p0.y + 2 * (1 - t) * t * p1.y + t ** 2 * p2.y;
    ctx.lineTo(x * size, y * size);
  }

  ctx.stroke();
  ctx.restore();
}

function drawCornerSilhouette(ctx: CanvasRenderingContext2D, size: number) {
  ctx.save();
  ctx.strokeStyle = colors.steel;
  ctx.lineWidth = 1;
  ctx.globalAlpha = 0.2;

  // Outer wall
  ctx.beginPath();
  ctx.arc(size, 0, size * 0.95, Math.PI * 0.5, Math.PI, false);
  ctx.stroke();

  // Inner wall
  ctx.beginPath();
  ctx.arc(size, 0, size * 0.5, Math.PI * 0.5, Math.PI, false);
  ctx.stroke();

  ctx.restore();
}

export function CornerDrag({ onDeltaChange, className = '' }: CornerDragProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [points, setPoints] = useState<ControlPoint[]>(INITIAL);
  const [dragging, setDragging] = useState<number | null>(null);
  const [hovering, setHovering] = useState<number | null>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = CANVAS_SIZE * dpr;
    canvas.height = CANVAS_SIZE * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);

    // Corner silhouette
    drawCornerSilhouette(ctx, CANVAS_SIZE);

    // Optimal line (ghost)
    drawBezier(ctx, OPTIMAL, CANVAS_SIZE, colors.chalk, 2, 0.1);

    // User line
    drawBezier(ctx, points, CANVAS_SIZE, colors.acidGreen, 3, 0.8);

    // Control points
    points.forEach((p, i) => {
      const x = p.x * CANVAS_SIZE;
      const y = p.y * CANVAS_SIZE;
      const isHovered = hovering === i;

      ctx.beginPath();
      ctx.arc(x, y, isHovered ? POINT_RADIUS * 1.3 : POINT_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = colors.acidGreen;
      ctx.globalAlpha = isHovered ? 1 : 0.7;
      ctx.fill();
      ctx.globalAlpha = 1;

      // Label
      ctx.font = '10px "IBM Plex Mono"';
      ctx.fillStyle = colors.chalk;
      ctx.textAlign = 'center';
      ctx.fillText(LABELS[i], x, y - POINT_RADIUS - 6);
    });
  }, [points, hovering]);

  useEffect(() => {
    render();
  }, [render]);

  // Compute and report delta
  useEffect(() => {
    const result = computeCornerDelta(points[0], points[1], points[2]);
    onDeltaChange(result.delta);
  }, [points, onDeltaChange]);

  const getCanvasPoint = (e: React.PointerEvent): ControlPoint => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    };
  };

  const findNearestPoint = (pos: ControlPoint): number | null => {
    for (let i = 0; i < points.length; i++) {
      const dx = pos.x - points[i].x;
      const dy = pos.y - points[i].y;
      if (Math.sqrt(dx * dx + dy * dy) < 0.08) return i;
    }
    return null;
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    const pos = getCanvasPoint(e);
    const idx = findNearestPoint(pos);
    if (idx !== null) {
      setDragging(idx);
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    }
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    const pos = getCanvasPoint(e);

    if (dragging !== null) {
      setPoints((prev) => {
        const next = [...prev];
        next[dragging] = {
          x: Math.max(0, Math.min(1, pos.x)),
          y: Math.max(0, Math.min(1, pos.y)),
        };
        return next;
      });
    } else {
      setHovering(findNearestPoint(pos));
    }
  };

  const handlePointerUp = () => {
    setDragging(null);
  };

  return (
    <div className={`relative ${className}`}>
      <canvas
        ref={canvasRef}
        className="w-full max-w-[400px] aspect-square cursor-grab active:cursor-grabbing"
        style={{ width: '100%', maxWidth: CANVAS_SIZE }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        aria-label="Drag the racing line control points to adjust the corner line"
        role="img"
      />
    </div>
  );
}
