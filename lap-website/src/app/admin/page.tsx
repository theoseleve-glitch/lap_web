"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-client";

type Metrics = {
  http: {
    total_24h: { total: number };
    errors_24h: { total: number };
    "5xx_24h": { total: number };
  };
  latency: { last_hour: { count: number; p50?: number; p95?: number } };
  jobs: { active: number; failed_24h: number; completed_24h: number };
};

type BillingOverview = {
  active_subscribers: number;
  plan_distribution: { plan_tier: string; subscription_status: string; cnt: number }[];
};

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-4">
      <p className="text-xs text-white/40">{label}</p>
      <p className="mt-1 text-2xl font-bold text-white">{value}</p>
      {sub && <p className="mt-1 text-xs text-white/30">{sub}</p>}
    </div>
  );
}

export default function AdminDashboard() {
  const { data: metrics } = useQuery({
    queryKey: ["admin-metrics"],
    queryFn: async () => {
      return await apiFetch<Metrics>("/admin/metrics");
    },
    refetchInterval: 30000,
  });

  const { data: billing } = useQuery({
    queryKey: ["admin-billing"],
    queryFn: async () => {
      return await apiFetch<BillingOverview>("/admin/billing/overview");
    },
    refetchInterval: 60000,
  });

  const errorRate =
    metrics && metrics.http.total_24h.total > 0
      ? (
          (metrics.http["5xx_24h"].total / metrics.http.total_24h.total) *
          100
        ).toFixed(1)
      : "0.0";

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-6 text-2xl font-bold text-white">Admin Dashboard</h1>

      <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Requests (24h)"
          value={metrics?.http.total_24h.total ?? "—"}
        />
        <MetricCard
          label="5xx Rate (24h)"
          value={`${errorRate}%`}
          sub={`${metrics?.http["5xx_24h"].total ?? 0} errors`}
        />
        <MetricCard
          label="Active Jobs"
          value={metrics?.jobs.active ?? "—"}
          sub={`${metrics?.jobs.completed_24h ?? 0} completed today`}
        />
        <MetricCard
          label="p95 Latency"
          value={
            metrics?.latency.last_hour.p95
              ? `${metrics.latency.last_hour.p95.toFixed(0)}ms`
              : "—"
          }
        />
      </div>

      <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-3">
        <MetricCard
          label="Active Subscribers"
          value={billing?.active_subscribers ?? "—"}
        />
        <MetricCard
          label="Failed Jobs (24h)"
          value={metrics?.jobs.failed_24h ?? "—"}
        />
        <MetricCard
          label="Error Requests (24h)"
          value={metrics?.http.errors_24h.total ?? "—"}
        />
      </div>

      {billing?.plan_distribution && billing.plan_distribution.length > 0 && (
        <div className="rounded-lg border border-white/10">
          <h2 className="border-b border-white/10 px-4 py-3 text-sm font-medium text-white/60">
            Plan Distribution
          </h2>
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs text-white/40">
                <th className="px-4 py-2">Tier</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 text-right">Count</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {billing.plan_distribution.map((row, i) => (
                <tr key={i} className="text-sm">
                  <td className="px-4 py-2 text-white">{row.plan_tier ?? "—"}</td>
                  <td className="px-4 py-2 text-white/60">
                    {row.subscription_status ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-white">{row.cnt}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
