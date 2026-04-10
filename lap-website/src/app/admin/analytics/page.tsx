'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';
import DauChart from '@/components/admin/DauChart';
import FeatureAdoptionChart from '@/components/admin/FeatureAdoptionChart';
import RetentionPanel from '@/components/admin/RetentionPanel';
import EventTimeline from '@/components/admin/EventTimeline';

type DauResponse = {
  days: { date: string; users: number; events: number }[];
  summary: {
    dau_today: number;
    wau_7d: number;
    total_events_30d: number;
    unique_features: number;
  };
};

type FeaturesResponse = {
  features: { event_type: string; count: number; unique_users: number }[];
};

type RetentionResponse = {
  cohorts: { week: string; size: number; retention: number[] }[];
};

type TimelineResponse = {
  events: {
    event_type: string;
    user_email: string;
    user_name: string | null;
    path: string;
    properties: Record<string, unknown>;
    created_at: string;
  }[];
};

type StorageResponse = {
  total_storage_bytes: number;
  avg_storage_per_session_bytes: number;
};

function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${(bytes / 1e3).toFixed(0)} KB`;
}

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

export default function AnalyticsPage() {
  const [period, setPeriod] = useState(30);

  const { data: dau } = useQuery({
    queryKey: ['admin-analytics-dau', period],
    queryFn: () => apiFetch<DauResponse>(`/admin/analytics/dau?days=${period}`),
    refetchInterval: 30000,
  });

  const { data: features } = useQuery({
    queryKey: ['admin-analytics-features'],
    queryFn: () => apiFetch<FeaturesResponse>('/admin/analytics/features?days=30'),
    refetchInterval: 60000,
  });

  const { data: retention } = useQuery({
    queryKey: ['admin-analytics-retention'],
    queryFn: () => apiFetch<RetentionResponse>('/admin/analytics/retention?weeks=8'),
    refetchInterval: 60000,
  });

  const { data: timeline } = useQuery({
    queryKey: ['admin-analytics-timeline'],
    queryFn: () => apiFetch<TimelineResponse>('/admin/analytics/timeline?limit=50'),
    refetchInterval: 30000,
  });

  const { data: storage } = useQuery({
    queryKey: ['admin-analytics-storage'],
    queryFn: () => apiFetch<StorageResponse>('/admin/analytics/storage'),
    refetchInterval: 60000,
  });

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-6 text-2xl font-bold text-white">Analytics</h1>

      {/* Summary bar — 6 cards */}
      <div className="mb-6 grid grid-cols-3 gap-4 md:grid-cols-6">
        <MetricCard label="DAU (Today)" value={dau?.summary?.dau_today ?? '—'} />
        <MetricCard label="WAU (7d)" value={dau?.summary?.wau_7d ?? '—'} />
        <MetricCard
          label="Events (30d)"
          value={dau?.summary?.total_events_30d?.toLocaleString() ?? '—'}
        />
        <MetricCard label="Features" value={dau?.summary?.unique_features ?? '—'} />
        <MetricCard
          label="Total Storage"
          value={storage ? formatBytes(storage.total_storage_bytes) : '—'}
        />
        <MetricCard
          label="Avg/User"
          value={storage ? formatBytes(storage.avg_storage_per_session_bytes) : '—'}
        />
      </div>

      {/* Charts */}
      <div className="space-y-6">
        <DauChart data={dau?.days ?? []} period={period} onPeriodChange={setPeriod} />
        <FeatureAdoptionChart data={features?.features ?? []} />
        <RetentionPanel data={retention?.cohorts ?? []} />
        <EventTimeline data={timeline?.events ?? []} />
      </div>
    </div>
  );
}
