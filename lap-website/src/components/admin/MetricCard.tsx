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

export function MetricCard({ label, value, sub, status = 'ok' }: MetricCardProps) {
  return (
    <div className={`rounded-lg border bg-concrete p-4 ${statusColors[status]}`}>
      <p className="text-xs text-steel">{label}</p>
      <p className="mt-1 text-2xl font-bold text-chalk">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-steel/60">{sub}</p>}
    </div>
  );
}
