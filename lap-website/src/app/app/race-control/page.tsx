'use client';

import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function RaceControlDashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ['admin-health'],
    queryFn: adminApi.healthOverview,
    refetchInterval: 30000,
  });

  if (isLoading) {
    return <p className="text-steel">Loading health overview...</p>;
  }

  return (
    <div>
      <h1 className="mb-6 text-xl font-bold text-chalk">Health Overview</h1>

      {/* Services status */}
      <div className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-steel">Services</h2>
        <div className="flex gap-3">
          {data?.services &&
            Object.entries(data.services).map(([name, status]) => (
              <div key={name} className="flex items-center gap-1.5">
                <span
                  className={`h-2 w-2 rounded-full ${
                    status === 'ok' ? 'bg-green-400' : 'bg-red-400'
                  }`}
                />
                <span className="text-sm text-chalk/70">{name}</span>
              </div>
            ))}
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Jobs (24h)"
          value={data?.jobs?.total_24h ?? 0}
          sub={`${data?.jobs?.failed_24h ?? 0} failed, ${data?.jobs?.queue_depth ?? 0} queued`}
          status={
            (data?.jobs?.failure_rate_pct ?? 0) > 10
              ? 'error'
              : (data?.jobs?.failure_rate_pct ?? 0) > 5
                ? 'warning'
                : 'ok'
          }
        />
        <MetricCard
          label="Avg Duration"
          value={`${(data?.jobs?.avg_duration_s ?? 0).toFixed(1)}s`}
          status="ok"
        />
        <MetricCard
          label="Webhook Success"
          value={`${data?.billing?.webhook_success_rate_pct ?? 100}%`}
          sub={`${data?.billing?.webhook_total_24h ?? 0} total`}
          status={
            (data?.billing?.webhook_success_rate_pct ?? 100) < 95
              ? 'error'
              : 'ok'
          }
        />
        <MetricCard
          label="Login Failures (24h)"
          value={data?.security?.login_failures_24h ?? 0}
          sub={`${data?.security?.rate_limits_24h ?? 0} rate limited`}
          status={
            (data?.security?.login_failures_24h ?? 0) > 50
              ? 'error'
              : (data?.security?.login_failures_24h ?? 0) > 20
                ? 'warning'
                : 'ok'
          }
        />
      </div>
    </div>
  );
}
