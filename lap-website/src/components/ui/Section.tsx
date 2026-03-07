/**
 * Section layout primitive — enforces consistent spacing rhythm.
 *
 * Usage:
 *   <Section size="lg" id="features">
 *     <SectionHeader eyebrow="S3" title="Product" />
 *     ...content...
 *   </Section>
 */

import { type ReactNode } from 'react';

type SectionSize = 'sm' | 'md' | 'lg' | 'xl';

const PADDING: Record<SectionSize, string> = {
  sm: 'py-12 md:py-16',     // 48-64px
  md: 'py-16 md:py-24',     // 64-96px
  lg: 'py-24 md:py-32',     // 96-128px
  xl: 'py-32 md:py-48',     // 128-192px
};

interface SectionProps {
  children: ReactNode;
  size?: SectionSize;
  id?: string;
  className?: string;
  /** Use grid-lap 12-column layout inside */
  grid?: boolean;
}

export function Section({ children, size = 'lg', id, className = '', grid = false }: SectionProps) {
  return (
    <section id={id} className={`${PADDING[size]} ${className}`}>
      {grid ? (
        <div className="grid-lap">{children}</div>
      ) : (
        children
      )}
    </section>
  );
}

interface SectionHeaderProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
}

export function SectionHeader({ eyebrow, title, subtitle }: SectionHeaderProps) {
  return (
    <div className="mb-12">
      {eyebrow && (
        <span className="font-telemetry text-xs tracking-widest uppercase text-steel block mb-3">
          {eyebrow}
        </span>
      )}
      <h2 className="font-monument text-[length:var(--text-h2)] leading-[0.85]">{title}</h2>
      {subtitle && (
        <p className="text-steel mt-4 max-w-2xl" style={{ fontSize: 'var(--text-body)' }}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
