'use client';

import type { ReactNode } from 'react';
import { useSplitText } from '@/hooks/useSplitText';
import { useReducedMotion } from '@/hooks/useReducedMotion';

interface MonumentTextProps {
  children: ReactNode;
  size?: 'xl' | 'h1' | 'h2' | 'h3';
  as?: 'h1' | 'h2' | 'h3' | 'p' | 'span';
  className?: string;
  reveal?: boolean;
  /** Enable per-character split-text animation (overrides reveal) */
  split?: boolean;
  /** Use scroll-scrub instead of triggered animation */
  scrub?: boolean;
}

const sizeMap = {
  xl: 'var(--text-monument-xl)',
  h1: 'var(--text-h1)',
  h2: 'var(--text-h2)',
  h3: 'var(--text-h3)',
};

export function MonumentText({
  children,
  size = 'h1',
  as: Tag = 'h2',
  className = '',
  reveal = false,
  split = false,
  scrub = false,
}: MonumentTextProps) {
  const { reducedMotion } = useReducedMotion();
  const splitRef = useSplitText<HTMLElement>({
    disabled: !split || reducedMotion,
    scrub,
    stagger: 0.015,
    start: 'top 85%',
  });

  return (
    <Tag
      ref={split ? splitRef : undefined}
      className={`font-monument ${className}`}
      style={{ fontSize: sizeMap[size], perspective: split ? '600px' : undefined }}
      {...(reveal && !split ? { 'data-monument-reveal': '' } : {})}
    >
      {children}
    </Tag>
  );
}
