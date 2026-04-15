/**
 * ChartBody — wraps the canvas (or other render target) with consistent
 * sizing behaviour. Use `fillParent` for charts that should take all
 * available vertical space (in flex layouts), or `aspect` for charts with
 * a fixed aspect ratio (G-G diagram).
 */

import type { ReactNode } from 'react';

export interface ChartBodyProps {
  children: ReactNode;
  /**
   * Layout mode:
   *  - 'fixed':   takes a fixed pixel height (default 240)
   *  - 'fill':    grows to fill its flex parent
   *  - 'aspect':  maintains an aspect ratio (e.g. "1 / 1" for square)
   */
  layout?: 'fixed' | 'fill' | 'aspect';
  height?: number;
  aspect?: string;
  /** ARIA label describing what the chart shows. */
  'aria-label'?: string;
}

export function ChartBody({
  children,
  layout = 'fixed',
  height = 240,
  aspect = '16 / 9',
  'aria-label': ariaLabel,
}: ChartBodyProps) {
  const style: React.CSSProperties =
    layout === 'fixed'
      ? { height }
      : layout === 'aspect'
        ? { aspectRatio: aspect }
        : { flex: '1 1 0%', minHeight: 0 };

  return (
    <div
      className="relative w-full overflow-hidden"
      style={style}
      role={ariaLabel ? 'img' : undefined}
      aria-label={ariaLabel}
    >
      {children}
    </div>
  );
}
