'use client';

interface MetricCardProps {
  label: string;
  value: string | number;
  sub?: string;
  status?: 'ok' | 'warning' | 'error';
}

const statusColors = {
  ok: 'border-green-500/30',
  warning: 'border-amber-500/30',
  error: 'border-red-500/30',
};

const statusIcons = {
  ok: { symbol: '✓', color: 'text-green-400' },
  warning: { symbol: '⚠', color: 'text-amber-400' },
  error: { symbol: '✕', color: 'text-red-400' },
};

export function MetricCard({ label, value, sub, status = 'ok' }: MetricCardProps) {
  const icon = statusIcons[status];
  return (
    <div className={`rounded-lg border bg-concrete p-4 ${statusColors[status]}`}>
      <div className="flex items-center justify-between">
        <p className="text-xs text-steel">{label}</p>
        <span className={`text-xs ${icon.color}`} aria-label={`Status: ${status}`}>{icon.symbol}</span>
      </div>
      <p className="mt-1 text-2xl font-bold text-chalk">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-steel/60">{sub}</p>}
    </div>
  );
}
