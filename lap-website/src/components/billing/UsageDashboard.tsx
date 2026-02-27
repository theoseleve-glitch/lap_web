'use client';

import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';

interface UsageMetric {
  used: number;
  limit: number | null;
  remaining: number | null;
}

interface UsageData {
  period: string;
  days_until_reset: number;
  reports: UsageMetric;
  uploads: UsageMetric;
  api_calls: UsageMetric;
  storage_mb: UsageMetric;
}

/**
 * Circular progress ring for visualizing quota usage.
 */
function CircularProgress({
  used,
  limit,
  label,
  className = '',
}: {
  used: number;
  limit: number | null;
  label: string;
  className?: string;
}) {
  const isUnlimited = limit === null || limit === -1;
  const percentage = isUnlimited ? 0 : limit === 0 ? 100 : Math.min(100, (used / limit) * 100);

  // Color coding: green (<50%), yellow (50-80%), red (>80%), gray (unlimited)
  let strokeColor = 'stroke-acid-green';
  let textColor = 'text-acid-green';
  if (isUnlimited) {
    strokeColor = 'stroke-steel/30';
    textColor = 'text-steel';
  } else if (percentage > 80) {
    strokeColor = 'stroke-safety-red';
    textColor = 'text-safety-red';
  } else if (percentage > 50) {
    strokeColor = 'stroke-marshal-yellow';
    textColor = 'text-marshal-yellow';
  }

  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percentage / 100) * circumference;

  return (
    <div className={`flex flex-col items-center gap-2 ${className}`}>
      <div className="relative w-24 h-24">
        <svg className="w-full h-full -rotate-90" viewBox="0 0 80 80">
          {/* Background ring */}
          <circle
            cx="40" cy="40" r={radius}
            fill="none" strokeWidth="6"
            className="stroke-steel/10"
          />
          {/* Progress ring */}
          {!isUnlimited && (
            <circle
              cx="40" cy="40" r={radius}
              fill="none" strokeWidth="6" strokeLinecap="round"
              className={strokeColor}
              style={{
                strokeDasharray: circumference,
                strokeDashoffset: offset,
                transition: 'stroke-dashoffset 0.5s ease',
              }}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={`font-telemetry text-lg ${textColor}`}>
            {isUnlimited ? '∞' : `${used}`}
          </span>
          {!isUnlimited && limit !== null && (
            <span className="font-telemetry text-[10px] text-steel">
              / {limit}
            </span>
          )}
        </div>
      </div>
      <span className="font-body text-xs text-steel text-center">{label}</span>
    </div>
  );
}

/**
 * Usage dashboard with circular progress indicators for each quota.
 */
export function UsageDashboard({ className = '' }: { className?: string }) {
  const { data, isLoading } = useQuery<UsageData>({
    queryKey: ['billing', 'usage'],
    queryFn: () => apiFetch<UsageData>('/billing/usage'),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className={`bg-concrete rounded-lg border border-steel/20 p-6 ${className}`}>
        <div className="animate-pulse flex gap-8 justify-center">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="w-24 h-32 bg-steel/10 rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className={`bg-concrete rounded-lg border border-steel/20 p-6 ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-monument text-sm text-chalk">Usage This Month</h3>
        <span className="font-telemetry text-xs text-steel">
          Resets in {data.days_until_reset} days
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <CircularProgress
          used={data.reports.used}
          limit={data.reports.limit}
          label="Reports"
        />
        <CircularProgress
          used={data.uploads.used}
          limit={data.uploads.limit}
          label="Uploads"
        />
        <CircularProgress
          used={data.api_calls.used}
          limit={data.api_calls.limit}
          label="API Calls"
        />
        <CircularProgress
          used={data.storage_mb.used}
          limit={data.storage_mb.limit}
          label="Storage (MB)"
        />
      </div>
    </div>
  );
}
