'use client';

import type { ReactNode } from 'react';

interface MonumentTextProps {
  children: ReactNode;
  size?: 'xl' | 'h1' | 'h2' | 'h3';
  as?: 'h1' | 'h2' | 'h3' | 'p' | 'span';
  className?: string;
  reveal?: boolean;
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
}: MonumentTextProps) {
  return (
    <Tag
      className={`font-monument ${className}`}
      style={{ fontSize: sizeMap[size] }}
      {...(reveal ? { 'data-monument-reveal': '' } : {})}
    >
      {children}
    </Tag>
  );
}
