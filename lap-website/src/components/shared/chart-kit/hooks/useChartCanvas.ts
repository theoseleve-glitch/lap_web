/**
 * useChartCanvas — DPR-safe canvas + ResizeObserver in a single hook.
 *
 * Every chart that draws to a canvas should use this. It handles:
 *  - device pixel ratio scaling (sharp on retina)
 *  - container resize (re-sizes canvas backing store)
 *  - re-running the consumer's draw callback on resize
 *  - exposing CSS width/height for layout math
 *
 * Consumers receive `{ canvasRef, containerRef, ready, width, height, dpr }`.
 * Call your draw function from a `useEffect` that depends on `ready`, `width`,
 * `height`, and your data — the hook itself does not call your draw fn,
 * because data dependencies belong to the consumer.
 *
 * The canvas is auto-styled `display:block` to avoid the inline-element
 * trailing-whitespace bug that adds 4px to canvas containers.
 */

'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

export interface ChartCanvas {
  containerRef: React.RefObject<HTMLDivElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  /** True once the container has measured a non-zero size. */
  ready: boolean;
  /** CSS pixel width of the container. */
  width: number;
  /** CSS pixel height of the container. */
  height: number;
  /** Device pixel ratio. */
  dpr: number;
}

export interface UseChartCanvasOptions {
  /** Optional callback fired after the canvas size is updated. */
  onResize?: (size: { width: number; height: number; dpr: number }) => void;
  /** Minimum dimensions. Below these, `ready` stays false. Default 1×1. */
  minWidth?: number;
  minHeight?: number;
}

export function useChartCanvas(opts: UseChartCanvasOptions = {}): ChartCanvas {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [dpr, setDpr] = useState<number>(() =>
    typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1,
  );

  const onResize = opts.onResize;
  const minWidth = opts.minWidth ?? 1;
  const minHeight = opts.minHeight ?? 1;

  // Apply size + DPR to the canvas backing store and inline style.
  const applySize = useCallback(
    (w: number, h: number, ratio: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      // Backing store
      canvas.width = Math.max(1, Math.round(w * ratio));
      canvas.height = Math.max(1, Math.round(h * ratio));
      // CSS size
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      canvas.style.display = 'block';
    },
    [],
  );

  // ResizeObserver — drives both layout and DPR refresh.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let frame = 0;
    const ro = new ResizeObserver((entries) => {
      // Coalesce multiple rapid resizes into one frame.
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const entry = entries[entries.length - 1];
        const cr = entry.contentRect;
        const w = Math.round(cr.width);
        const h = Math.round(cr.height);
        const currentDpr = window.devicePixelRatio || 1;

        applySize(w, h, currentDpr);
        setSize((prev) => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
        setDpr((prev) => (prev === currentDpr ? prev : currentDpr));
        onResize?.({ width: w, height: h, dpr: currentDpr });
      });
    });
    ro.observe(container);

    return () => {
      if (frame) cancelAnimationFrame(frame);
      ro.disconnect();
    };
  }, [applySize, onResize]);

  return {
    containerRef,
    canvasRef,
    ready: size.width >= minWidth && size.height >= minHeight,
    width: size.width,
    height: size.height,
    dpr,
  };
}
