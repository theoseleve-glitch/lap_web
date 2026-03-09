import type { ReactNode } from 'react';

type CardVariant = 'default' | 'outlined' | 'elevated';

interface CardProps {
  children: ReactNode;
  variant?: CardVariant;
  className?: string;
  as?: 'div' | 'article' | 'section';
}

const VARIANT_CLASSES: Record<CardVariant, string> = {
  default: 'bg-concrete border border-steel/10 rounded-xl',
  outlined: 'border border-steel/20 bg-concrete/30',
  elevated: 'bg-concrete border border-steel/10 rounded-xl shadow-lg',
};

export function Card({ children, variant = 'default', className = '', as: Tag = 'div' }: CardProps) {
  return <Tag className={`${VARIANT_CLASSES[variant]} p-4 ${className}`}>{children}</Tag>;
}

export function CardHeader({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`mb-3 ${className}`}>{children}</div>;
}

export function CardTitle({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <h3 className={`text-sm font-monument text-chalk ${className}`}>{children}</h3>;
}

export function CardContent({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={className}>{children}</div>;
}
