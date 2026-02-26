'use client';

import { useRef, useEffect } from 'react';

interface MonumentTextProps {
  children: React.ReactNode;
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
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!reveal || !ref.current) return;

    const el = ref.current;
    el.style.clipPath = 'inset(0 100% 0 0)';

    const loadGsap = async () => {
      const { gsap } = await import('gsap');
      gsap.to(el, {
        clipPath: 'inset(0 0% 0 0)',
        duration: 1.4,
        ease: 'power3.out',
        delay: 0.2,
      });
    };
    loadGsap();
  }, [reveal]);

  return (
    <Tag
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ref={ref as any}
      className={`font-monument ${className}`}
      style={{ fontSize: sizeMap[size] }}
    >
      {children}
    </Tag>
  );
}
