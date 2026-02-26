'use client';

import { type ReactNode } from 'react';

interface ChartPanelProps {
  title: string;
  subtitle?: string;
  loading?: boolean;
  error?: string | null;
  children: ReactNode;
  className?: string;
}

export function ChartPanel({
  title,
  subtitle,
  loading,
  error,
  children,
  className = '',
}: ChartPanelProps) {
  return (
    <div className={`bg-concrete rounded-lg border border-steel/20 ${className}`}>
      <div className="px-4 py-3 border-b border-steel/10">
        <h3 className="text-chalk font-body text-sm font-medium">{title}</h3>
        {subtitle && (
          <p className="text-steel font-telemetry text-xs mt-0.5">{subtitle}</p>
        )}
      </div>
      <div className="p-4">
        {loading ? (
          <div className="flex items-center justify-center h-48">
            <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-48">
            <p className="text-safety-red font-telemetry text-sm">{error}</p>
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
