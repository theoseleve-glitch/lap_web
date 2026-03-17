interface StatCardProps {
  label: string;
  value: string | number;
  unit?: string;
  trend?: 'up' | 'down' | 'neutral';
}

export function StatCard({ label, value, unit, trend }: StatCardProps) {
  const trendColor =
    trend === 'up' ? 'text-acid-green' :
    trend === 'down' ? 'text-safety-red' :
    'text-steel';

  return (
    <div className="bg-concrete rounded-lg border border-steel/20 p-4">
      <p className="text-steel font-telemetry text-xs uppercase tracking-wider mb-1">
        {label}
      </p>
      <div className="flex items-baseline gap-1 min-w-0">
        <span className={`font-monument text-2xl truncate ${trendColor}`}>
          {value}
        </span>
        {unit && (
          <span className="text-steel font-telemetry text-sm">{unit}</span>
        )}
      </div>
    </div>
  );
}
