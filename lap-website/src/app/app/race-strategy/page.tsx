'use client';

import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, DataTable } from '@/components/app';

interface RaceRow {
  race_id: number;
  race_name: string;
  track_name: string | null;
  team_name: string | null;
  race_duration_s: number;
  desired_stints: number;
  status: 'draft' | 'ready' | 'live' | 'finished';
  created_at: string;
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h${m.toString().padStart(2, '0')}` : `${m}m`;
}

const statusConfig: Record<string, { label: string; className: string }> = {
  draft: { label: 'DRAFT', className: 'text-steel bg-steel/10 border-steel/30' },
  ready: { label: 'READY', className: 'text-marshal-yellow bg-marshal-yellow/10 border-marshal-yellow/30' },
  live: { label: 'LIVE', className: 'text-acid-green bg-acid-green/10 border-acid-green/30 animate-pulse' },
  finished: { label: 'FINISHED', className: 'text-chalk bg-chalk/10 border-chalk/30' },
};

export default function RaceStrategyListPage() {
  const router = useRouter();

  const { data, isLoading } = useQuery({
    queryKey: ['race-strategy'],
    queryFn: () => api.get<{ races: RaceRow[] }>('/race-strategy/'),
  });

  const races = data?.races ?? [];

  const columns = [
    { key: 'race_name', header: 'Race', sortable: true },
    {
      key: 'track_name',
      header: 'Track',
      sortable: true,
      render: (row: RaceRow) => (row.track_name || '—') as ReactNode,
    },
    {
      key: 'team_name',
      header: 'Team',
      render: (row: RaceRow) => (row.team_name || '—') as ReactNode,
    },
    {
      key: 'race_duration_s',
      header: 'Duration',
      render: (row: RaceRow) => formatDuration(row.race_duration_s) as ReactNode,
    },
    { key: 'desired_stints', header: 'Stints' },
    {
      key: 'status',
      header: 'Status',
      render: (row: RaceRow) => {
        const cfg = statusConfig[row.status] || statusConfig.draft;
        return (
          <span
            className={`inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border ${cfg.className}`}
          >
            {cfg.label}
          </span>
        );
      },
    },
  ];

  return (
    <div>
      <PageHeader
        title="Race Strategy"
        subtitle="Endurance race management — plan, optimize, and run"
        actions={
          <Link
            href="/app/race-strategy/new"
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-pit-orange/80 transition-colors"
          >
            + New Race
          </Link>
        }
      />
      {isLoading ? (
        <div className="text-steel font-body p-8 text-center">Loading races...</div>
      ) : (
        <DataTable
          columns={columns}
          data={races}
          keyField="race_id"
          onRowClick={(row: RaceRow) => {
            if (row.status === 'live') {
              router.push(`/app/race-strategy/${row.race_id}/live`);
            } else if (row.status === 'finished') {
              router.push(`/app/race-strategy/${row.race_id}/summary`);
            } else {
              router.push(`/app/race-strategy/${row.race_id}`);
            }
          }}
          emptyMessage="No races yet. Create your first endurance race strategy."
        />
      )}
    </div>
  );
}
