'use client';

import Link from 'next/link';

interface StampButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
  className?: string;
  type?: 'button' | 'submit';
}

export function StampButton({
  children,
  onClick,
  href,
  className = '',
  type = 'button',
}: StampButtonProps) {
  const baseClass = `
    inline-flex items-center justify-center
    px-6 py-3
    border-2 border-chalk
    bg-transparent text-chalk
    font-telemetry text-[11px] tracking-[0.12em] uppercase
    transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]
    hover:bg-chalk hover:text-asphalt
    active:scale-[0.97]
    focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2
    ${className}
  `.trim();

  if (href) {
    if (href.startsWith('/')) {
      return (
        <Link href={href} className={baseClass} onClick={onClick}>
          {children}
        </Link>
      );
    }
    return (
      <a href={href} className={baseClass} onClick={onClick}>
        {children}
      </a>
    );
  }

  return (
    <button type={type} className={baseClass} onClick={onClick}>
      {children}
    </button>
  );
}
