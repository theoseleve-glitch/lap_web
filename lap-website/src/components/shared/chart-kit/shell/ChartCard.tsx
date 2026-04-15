/**
 * ChartCard — the shell every chart lives inside.
 *
 * Provides the only canonical chart surface treatment: dark concrete bg,
 * subtle steel border, controlled corner radius, consistent inner padding.
 *
 * Density variants:
 *  - "comfortable" (default): primary charts, more breathing room
 *  - "compact": tertiary or dense rows, tighter rhythm
 *
 * Tone variants control the left edge accent — used sparingly to mark
 * the visual anchor of a section without resorting to background color.
 */

import type { ReactNode } from 'react';
import { type Density } from '../tokens';

export type CardTone = 'default' | 'primary' | 'reference';

export interface ChartCardProps {
  children: ReactNode;
  density?: Density;
  tone?: CardTone;
  /** Overrides the section's height. Most charts let content drive height. */
  fixedHeight?: number | string;
  /** aria-label override. If omitted, the ChartHeader's title is used. */
  'aria-label'?: string;
  /** Required only if you don't render a ChartHeader inside. */
  id?: string;
}

const DENSITY_PADDING: Record<Density, string> = {
  comfortable: 'p-4',
  compact: 'p-3',
};

const TONE_BORDER: Record<CardTone, string> = {
  default: 'border-steel/15',
  primary: 'border-steel/15 border-l-pit-orange/40 border-l-2',
  reference: 'border-steel/15 border-l-racing-purple/40 border-l-2',
};

export function ChartCard({
  children,
  density = 'comfortable',
  tone = 'default',
  fixedHeight,
  id,
  'aria-label': ariaLabel,
}: ChartCardProps) {
  return (
    <section
      id={id}
      aria-label={ariaLabel}
      className={`relative bg-concrete border ${TONE_BORDER[tone]} rounded-xl ${DENSITY_PADDING[density]} flex flex-col h-full w-full`}
      style={fixedHeight != null ? { height: fixedHeight } : undefined}
      data-density={density}
    >
      {children}
    </section>
  );
}
