import type { ReactNode } from 'react';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'neutral';

interface BadgeProps {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  default: 'border-acid-green/40 text-acid-green bg-acid-green/10',
  success: 'border-acid-green/40 text-acid-green bg-acid-green/10',
  warning: 'border-marshal-yellow/40 text-marshal-yellow bg-marshal-yellow/10',
  danger: 'border-safety-red/40 text-safety-red bg-safety-red/10',
  info: 'border-racing-purple/40 text-racing-purple bg-racing-purple/10',
  neutral: 'border-steel/30 text-steel bg-steel/10',
};

export function Badge({ children, variant = 'default', className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center border px-2 py-0.5 text-[10px] font-telemetry uppercase tracking-wider leading-tight ${VARIANT_CLASSES[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
