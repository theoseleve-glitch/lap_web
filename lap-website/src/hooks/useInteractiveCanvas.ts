'use client';
import React, { useEffect, useRef, useCallback, useState } from 'react';

/* ─── Types ───────────────────────────────────────────────────────────── */

export interface CanvasSize {
  width: number;
  height: number;
}

export interface HoverPoint {
  /** Mouse X in CSS pixels (relative to canvas) */
  x: number;
  /** Mouse Y in CSS pixels (relative to canvas) */
  y: number;
  /** Normalized X (0..1 across plot area) */
  nx: number;
  /** Normalized Y (0..1 across plot area) */
  ny: number;
}

export interface TooltipData {
  /** Lines to display */
  lines: { label: string; value: string; color?: string }[];
  /** Optional header */
  header?: string;
}

export interface ChartPadding {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

interface UseInteractiveCanvasOptions {
  /** Called to draw the chart. Receives ctx, CSS width/height, and optional hover point. */
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number, hover: HoverPoint | null) => void;
  /** Dependencies for redraw (e.g., data). */
  deps: unknown[];
  /** Chart padding for normalizing hover coordinates. */
  padding?: ChartPadding;
  /** Callback to generate tooltip data from a hover point. */
  getTooltipData?: (hover: HoverPoint) => TooltipData | null;
  /** Whether to draw a vertical crosshair line at the hover x position. */
  crosshair?: boolean;
  /** Crosshair color (default: rgba(182, 255, 46, 0.4)) */
  crosshairColor?: string;
}

interface UseInteractiveCanvasResult {
  canvasRef: React.RefObject<HTMLCanvasElement>;
  containerRef: React.RefObject<HTMLDivElement>;
  tooltip: (TooltipData & { x: number; y: number }) | null;
  size: CanvasSize;
}

/* ─── Default Padding ─────────────────────────────────────────────────── */

const DEFAULT_PADDING: ChartPadding = { top: 10, right: 15, bottom: 30, left: 45 };

/* ─── Hook ────────────────────────────────────────────────────────────── */

export function useInteractiveCanvas({
  draw,
  deps,
  padding = DEFAULT_PADDING,
  getTooltipData,
  crosshair = false,
  crosshairColor = 'rgba(182, 255, 46, 0.4)',
}: UseInteractiveCanvasOptions): UseInteractiveCanvasResult {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<CanvasSize>({ width: 0, height: 0 });
  const [tooltip, setTooltip] = useState<(TooltipData & { x: number; y: number }) | null>(null);
  const hoverRef = useRef<HoverPoint | null>(null);
  const drawRef = useRef(draw);
  const getTooltipRef = useRef(getTooltipData);
  const paddingRef = useRef(padding);

  // Keep refs up to date
  drawRef.current = draw;
  getTooltipRef.current = getTooltipData;
  paddingRef.current = padding;

  // Core render function
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    // Draw the chart
    drawRef.current(ctx, w, h, hoverRef.current);

    // Draw crosshair if enabled and hovering
    if (crosshair && hoverRef.current) {
      const pad = paddingRef.current;
      const hx = hoverRef.current.x;
      if (hx >= pad.left && hx <= w - pad.right) {
        ctx.save();
        ctx.strokeStyle = crosshairColor;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(hx, pad.top);
        ctx.lineTo(hx, h - pad.bottom);
        ctx.stroke();
        ctx.restore();
      }
    }

    if (w !== size.width || h !== size.height) {
      setSize({ width: w, height: h });
    }
  }, [crosshair, crosshairColor, size.width, size.height]);

  // ResizeObserver for container
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ro = new ResizeObserver(() => {
      render();
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, [render]);

  // Redraw when deps change
  useEffect(() => {
    render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, render]);

  // Mouse event handlers
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const pad = paddingRef.current;
      const plotW = Math.max(rect.width - pad.left - pad.right, 1);
      const plotH = Math.max(rect.height - pad.top - pad.bottom, 1);
      const nx = Math.max(0, Math.min(1, (x - pad.left) / plotW));
      const ny = Math.max(0, Math.min(1, (y - pad.top) / plotH));

      hoverRef.current = { x, y, nx, ny };

      // Generate tooltip
      if (getTooltipRef.current) {
        const td = getTooltipRef.current(hoverRef.current);
        if (td) {
          setTooltip({ ...td, x: e.clientX - rect.left, y: e.clientY - rect.top });
        } else {
          setTooltip(null);
        }
      }

      render();
    };

    const handleMouseLeave = () => {
      hoverRef.current = null;
      setTooltip(null);
      render();
    };

    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseleave', handleMouseLeave);
    return () => {
      canvas.removeEventListener('mousemove', handleMouseMove);
      canvas.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [render]);

  return {
    canvasRef: canvasRef as unknown as React.RefObject<HTMLCanvasElement>,
    containerRef: containerRef as unknown as React.RefObject<HTMLDivElement>,
    tooltip,
    size,
  };
}
