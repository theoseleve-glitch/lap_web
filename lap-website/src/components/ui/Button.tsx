'use client';

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import Link from 'next/link';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'destructive';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  children: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  href?: string;
  loading?: boolean;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: [
    'border-2 border-pit-orange bg-pit-orange text-asphalt font-bold',
    'hover:brightness-110 hover:shadow-e2',
  ].join(' '),
  secondary: [
    'border-2 border-chalk bg-transparent text-chalk',
    'hover:bg-chalk hover:text-asphalt hover:shadow-e1',
  ].join(' '),
  ghost: [
    'border border-steel/40 bg-transparent text-steel',
    'hover:text-chalk hover:border-steel',
  ].join(' '),
  destructive: [
    'border-2 border-safety-red bg-safety-red text-chalk font-bold',
    'hover:brightness-110 hover:shadow-e2',
  ].join(' '),
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'min-h-[36px] px-4 py-1.5 text-[11px]',
  md: 'min-h-[44px] px-6 py-2.5 text-[12px]',
  lg: 'min-h-[48px] px-8 py-3.5 text-[12px]',
};

const BASE_CLASSES = [
  'inline-flex items-center justify-center gap-2',
  'font-telemetry tracking-[0.12em] uppercase',
  'transition-all duration-[420ms] ease-[cubic-bezier(0.16,1,0.3,1)]',
  'active:scale-[0.98]',
  'focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--accent)] focus-visible:outline-offset-2',
  'disabled:opacity-40 disabled:pointer-events-none',
].join(' ');

function Spinner() {
  return (
    <svg
      className="animate-spin h-4 w-4"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" opacity="0.25" />
      <path d="M8 2a6 6 0 014.9 9.4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { children, variant = 'primary', size = 'md', href, loading, disabled, className = '', type = 'button', ...rest },
  ref,
) {
  const classes = `${BASE_CLASSES} ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`.trim();
  const isDisabled = disabled || loading;

  if (href) {
    if (href.startsWith('/')) {
      return (
        <Link
          href={href}
          className={classes}
          aria-disabled={isDisabled || undefined}
          tabIndex={isDisabled ? -1 : undefined}
        >
          {loading && <Spinner />}
          {children}
        </Link>
      );
    }
    return (
      <a
        href={href}
        className={classes}
        aria-disabled={isDisabled || undefined}
        tabIndex={isDisabled ? -1 : undefined}
      >
        {loading && <Spinner />}
        {children}
      </a>
    );
  }

  return (
    <button
      ref={ref}
      type={type}
      className={classes}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
});
