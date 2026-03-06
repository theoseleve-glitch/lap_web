'use client';

import Link from 'next/link';

export type StampVariant = 'primary' | 'secondary';

interface StampButtonProps {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
  className?: string;
  type?: 'button' | 'submit';
  /** Lint-enforced: max 1 primary per page. Defaults to 'primary' for backwards compat. */
  variant?: StampVariant;
}

export function StampButton({
  children,
  onClick,
  href,
  className = '',
  type = 'button',
  variant = 'primary',
}: StampButtonProps) {
  const isPrimary = variant === 'primary';
  const baseClass = `
    inline-flex items-center justify-center
    min-h-[48px] px-8 py-3.5
    border-2 ${isPrimary ? 'border-chalk' : 'border-steel/40'}
    bg-transparent ${isPrimary ? 'text-chalk' : 'text-steel'}
    font-telemetry text-[12px] tracking-[0.12em] uppercase
    shadow-[inset_0_0_0_1px_rgba(240,237,229,0.1)]
    transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]
    ${isPrimary ? 'hover:bg-chalk hover:text-asphalt hover:shadow-[0_0_24px_rgba(240,237,229,0.12)]' : 'hover:text-chalk hover:border-steel'}
    active:scale-[0.98]
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
