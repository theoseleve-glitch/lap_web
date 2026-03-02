'use client';

import { useRef, useState, useCallback } from 'react';
import Link from 'next/link';

interface PitButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
  className?: string;
  type?: 'button' | 'submit';
}

export function PitButton({
  children,
  onClick,
  href,
  className = '',
  type = 'button',
}: PitButtonProps) {
  const magnetRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const rafRef = useRef(false);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (rafRef.current) return;
    rafRef.current = true;
    requestAnimationFrame(() => {
      const rect = magnetRef.current?.getBoundingClientRect();
      if (rect) {
        const x = e.clientX - rect.left - rect.width / 2;
        const y = e.clientY - rect.top - rect.height / 2;
        setOffset({ x: x * 0.2, y: y * 0.2 });
      }
      rafRef.current = false;
    });
  }, []);

  const handleMouseLeave = useCallback(() => {
    setOffset({ x: 0, y: 0 });
  }, []);

  const baseClass = `
    inline-flex items-center justify-center
    min-h-[48px] px-8 py-3.5
    border-2 border-pit-orange
    bg-pit-orange text-asphalt
    font-telemetry text-[12px] tracking-[0.12em] uppercase font-bold
    shadow-[0_0_20px_rgba(201,168,76,0.15),2px_2px_0_rgba(240,237,229,0.12)]
    transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]
    hover:brightness-110 hover:shadow-[0_0_32px_rgba(201,168,76,0.25),2px_2px_0_rgba(240,237,229,0.2)]
    active:scale-[0.98]
    focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2
    ${className}
  `.trim();

  const magnetStyle = {
    transform: `translate(${offset.x}px, ${offset.y}px)`,
    transition: offset.x === 0 && offset.y === 0
      ? 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1)'
      : 'transform 0.15s ease-out',
  };

  const inner = href ? (
    href.startsWith('/') ? (
      <Link href={href} className={baseClass} onClick={onClick}>
        {children}
      </Link>
    ) : (
      <a href={href} className={baseClass} onClick={onClick}>
        {children}
      </a>
    )
  ) : (
    <button type={type} className={baseClass} onClick={onClick}>
      {children}
    </button>
  );

  return (
    <div
      ref={magnetRef}
      className="inline-block p-4 -m-4"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <div style={magnetStyle}>
        {inner}
      </div>
    </div>
  );
}
