/**
 * useChartPointer — bridges canvas pointer events to the global hover store.
 *
 * Every chart that wants distance-synced hover (the cross-chart crosshair
 * behaviour we already have) should use this hook instead of wiring up
 * mousemove + chart-hover-store by hand.
 *
 * Consumers provide:
 *  - source: a unique string identifying this chart in the hover bus
 *  - getBounds: returns the current plot rect + x-scale (function so it can
 *    pick up the latest values without re-subscribing)
 *
 * The hook returns the currently-broadcast hover distance (which may be
 * from this chart OR another in the same sync group). Re-render triggers
 * are managed via React state, so consumers' draw callbacks should depend
 * on the returned `hoverDistance`.
 */

'use client';

import { useEffect, useState, useRef, type RefObject } from 'react';
import { useChartHoverStore } from '@/lib/chart-hover-store';
import type { LinearScale } from '../scales';
import type { PlotRect } from '../primitives/drawAxis';

export interface ChartPointerBounds {
  plot: PlotRect;
  xScale: LinearScale;
}

export interface UseChartPointerOptions {
  /** A stable identifier — used to filter out echo events from this chart. */
  source: string;
  /** Returns the current plot bounds + x-scale. Called on every pointer move. */
  getBounds: () => ChartPointerBounds | null;
  /** When false, the hook does not attach listeners. Default true. */
  enabled?: boolean;
}

export interface ChartPointerState {
  /** Current shared hover distance (in domain units), or null. */
  hoverDistance: number | null;
  /** True when this chart is the originator of the current hover. */
  isHoverSource: boolean;
}

export function useChartPointer(
  canvasRef: RefObject<HTMLCanvasElement | null>,
  opts: UseChartPointerOptions,
): ChartPointerState {
  const { source, getBounds, enabled = true } = opts;
  const [state, setState] = useState<ChartPointerState>({
    hoverDistance: null,
    isHoverSource: false,
  });

  // Keep getBounds stable in a ref so we don't re-attach listeners on every render.
  const getBoundsRef = useRef(getBounds);
  getBoundsRef.current = getBounds;

  // Subscribe to the shared store
  useEffect(() => {
    return useChartHoverStore.subscribe((store) => {
      setState({
        hoverDistance: store.hoverDistance,
        isHoverSource: store.hoverSource === source,
      });
    });
  }, [source]);

  // Attach / detach pointer listeners
  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const setHover = useChartHoverStore.getState().setHover;
    const clearHover = useChartHoverStore.getState().clearHover;

    const handleMove = (e: PointerEvent) => {
      const bounds = getBoundsRef.current();
      if (!bounds) return;
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      // Outside the plot area horizontally — clear
      if (px < bounds.plot.left || px > bounds.plot.left + bounds.plot.width) {
        clearHover();
        return;
      }
      const distance = bounds.xScale.fromPixel(px);
      setHover(distance, source);
    };
    const handleLeave = () => clearHover();

    canvas.addEventListener('pointermove', handleMove);
    canvas.addEventListener('pointerleave', handleLeave);
    return () => {
      canvas.removeEventListener('pointermove', handleMove);
      canvas.removeEventListener('pointerleave', handleLeave);
    };
  }, [canvasRef, source, enabled]);

  return state;
}
