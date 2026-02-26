'use client';

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
  const baseClass = `
    inline-flex items-center justify-center
    px-8 py-4
    border-2 border-pit-orange
    bg-pit-orange text-asphalt
    font-telemetry text-[11px] tracking-[0.12em] uppercase font-bold
    transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]
    hover:brightness-110 hover:shadow-[0_0_24px_rgba(255,106,0,0.4)]
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
