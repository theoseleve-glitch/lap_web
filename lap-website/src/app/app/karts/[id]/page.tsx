'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable, QueryError, SkeletonStatCards, SkeletonBox, SkeletonTableRows } from '@/components/app';

interface KartDetail {
  id: number;
  name: string;
  number: string | null;
  chassis: string | null;
  engine: string | null;
  weight_kg: number | null;
  notes: string | null;
  sessions_count: number;
  best_time: number | null;
  avg_score: number | null;
}

interface SessionRow {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  score: number | null;
}

function formatTime(s: number | null): string {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-pit-orange';
  return 'text-safety-red';
}

export default function KartDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const { data: kart, isLoading: kartLoading, error: kartError, refetch } = useQuery({
    queryKey: ['kart', id],
    queryFn: () => api.get<KartDetail>(`/karts/${id}`),
  });

  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ['kart-sessions', id],
    queryFn: () => api.get<{ sessions: SessionRow[] }>(`/karts/${id}/sessions`),
    enabled: !!kart,
  });

  const sessions = sessionsData?.sessions ?? [];
  const isLoading = kartLoading || sessionsLoading;

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-40 mb-2" />
          <SkeletonBox className="h-3 w-24" />
        </div>
        <SkeletonStatCards count={3} />
        <SkeletonTableRows rows={4} cols={6} />
      </div>
    );
  }

  if (kartError) {
    return <QueryError message="Couldn't load kart details." onRetry={() => refetch()} />;
  }

  if (!kart) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Kart not found</h2>
        <p className="text-steel font-body text-sm mb-4">This kart may have been deleted or the link is invalid.</p>
        <Link href="/app/karts" className="text-pit-orange font-telemetry text-xs hover:underline">
          Back to karts
        </Link>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={kart.name}
        subtitle={[kart.chassis, kart.engine].filter(Boolean).join(' · ') || 'Kart details'}
        actions={
          <Link
            href="/app/karts"
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            ← All Karts
          </Link>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Sessions" value={kart.sessions_count} />
        <StatCard label="Best Time" value={formatTime(kart.best_time)} />
        <StatCard
          label="Avg Score"
          value={kart.avg_score != null ? kart.avg_score.toFixed(1) : '—'}
          trend={
            kart.avg_score == null ? 'neutral' :
            kart.avg_score >= 80 ? 'up' :
            kart.avg_score >= 60 ? 'neutral' : 'down'
          }
        />
      </div>

      {(kart.number || kart.weight_kg || kart.notes) && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-4 mb-6">
          <h2 className="font-telemetry text-xs uppercase tracking-wider text-steel mb-3">Details</h2>
          <dl className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {kart.number && (
              <div>
                <dt className="text-steel font-telemetry text-xs uppercase">Number</dt>
                <dd className="text-chalk font-body mt-0.5">#{kart.number}</dd>
              </div>
            )}
            {kart.chassis && (
              <div>
                <dt className="text-steel font-telemetry text-xs uppercase">Chassis</dt>
                <dd className="text-chalk font-body mt-0.5">{kart.chassis}</dd>
              </div>
            )}
            {kart.engine && (
              <div>
                <dt className="text-steel font-telemetry text-xs uppercase">Engine</dt>
                <dd className="text-chalk font-body mt-0.5">{kart.engine}</dd>
              </div>
            )}
            {kart.weight_kg && (
              <div>
                <dt className="text-steel font-telemetry text-xs uppercase">Weight</dt>
                <dd className="text-chalk font-body mt-0.5">{kart.weight_kg} kg</dd>
              </div>
            )}
          </dl>
          {kart.notes && (
            <div className="mt-3 pt-3 border-t border-steel/10">
              <dt className="text-steel font-telemetry text-xs uppercase mb-1">Notes</dt>
              <dd className="text-chalk font-body text-sm">{kart.notes}</dd>
            </div>
          )}
        </div>
      )}

      <h2 className="font-monument text-lg text-chalk mb-3">Session History</h2>
      <DataTable
        columns={[
          { key: 'date', header: 'Date', sortable: true },
          { key: 'track_name', header: 'Track', sortable: true },
          { key: 'driver_name', header: 'Driver', sortable: true },
          { key: 'laps', header: 'Laps', sortable: true, className: 'font-telemetry text-right' },
          {
            key: 'best_time',
            header: 'Best Time',
            sortable: true,
            className: 'font-telemetry',
            render: (row: SessionRow) => (
              <span className="text-acid-green">{formatTime(row.best_time)}</span>
            ),
          },
          {
            key: 'score',
            header: 'Score',
            sortable: true,
            className: 'font-telemetry text-right',
            render: (row: SessionRow) => (
              <span className={scoreColor(row.score)}>
                {row.score != null ? row.score.toFixed(1) : '—'}
              </span>
            ),
          },
        ]}
        data={sessions}
        keyField="id"
        onRowClick={(row) => router.push(`/app/sessions/${row.id}`)}
        emptyMessage="No sessions recorded for this kart yet."
      />
    </div>
  );
}
