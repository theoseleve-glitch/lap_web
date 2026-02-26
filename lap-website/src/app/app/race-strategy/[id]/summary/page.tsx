'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable, ChartPanel } from '@/components/app';

interface StintSummary {
  stint_number: number;
  compound: string;
  laps: number;
  avg_time: number;
  best_time: number;
  degradation_rate: number;
}

interface RaceSummary {
  id: number;
  name: string;
  track_name: string;
  total_time: number;
  total_laps: number;
  best_lap: number;
  best_lap_number: number;
  avg_lap: number;
  consistency_pct: number;
  pit_stops: number;
  time_in_pits: number;
  stints: StintSummary[];
}

function formatTime(s: number): string {
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
}

const compoundColors: Record<string, string> = {
  soft: '#FF2A2A',
  medium: '#FFD400',
  hard: '#F3F0E8',
  wet: '#3B82F6',
  inter: '#22C55E',
};

export default function RaceStrategySummaryPage() {
  const { id } = useParams<{ id: string }>();

  const { data: summary, isLoading } = useQuery({
    queryKey: ['race-strategy', id, 'summary'],
    queryFn: () => api.get<RaceSummary>(`/race-strategy/${id}/summary`),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!summary) return <div className="text-steel font-body">Summary not found</div>;

  return (
    <div>
      <PageHeader
        title={`${summary.name} — Summary`}
        subtitle={`${summary.track_name} · ${summary.total_laps} laps`}
        actions={
          <Link
            href={`/app/race-strategy/${id}`}
            className="px-3 py-1.5 border border-steel/30 text-steel font-telemetry text-xs rounded hover:text-chalk transition-colors"
          >
            Back to Strategy
          </Link>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Race Time" value={formatTime(summary.total_time)} />
        <StatCard label="Best Lap" value={formatTime(summary.best_lap)} trend="up" />
        <StatCard label="Avg Lap" value={formatTime(summary.avg_lap)} />
        <StatCard
          label="Consistency"
          value={`${summary.consistency_pct.toFixed(1)}%`}
          trend={summary.consistency_pct >= 90 ? 'up' : 'neutral'}
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Pit Stops" value={summary.pit_stops} />
        <StatCard label="Time in Pits" value={`${summary.time_in_pits.toFixed(1)}s`} />
        <StatCard label="Best Lap #" value={`L${summary.best_lap_number}`} />
      </div>

      {/* Stint breakdown */}
      <div className="mb-6">
        <h2 className="font-body text-chalk text-lg mb-3">Stint Breakdown</h2>
        <DataTable
          columns={[
            {
              key: 'stint_number',
              header: 'Stint',
              className: 'font-telemetry',
            },
            {
              key: 'compound',
              header: 'Compound',
              render: (row: StintSummary) => (
                <span
                  className="font-telemetry text-sm uppercase"
                  style={{ color: compoundColors[row.compound] ?? '#8A8F98' }}
                >
                  {row.compound}
                </span>
              ),
            },
            {
              key: 'laps',
              header: 'Laps',
              className: 'font-telemetry text-right',
            },
            {
              key: 'best_time',
              header: 'Best',
              className: 'font-telemetry',
              render: (row: StintSummary) => (
                <span className="text-acid-green">{row.best_time.toFixed(3)}s</span>
              ),
            },
            {
              key: 'avg_time',
              header: 'Average',
              className: 'font-telemetry',
              render: (row: StintSummary) => <span>{row.avg_time.toFixed(3)}s</span>,
            },
            {
              key: 'degradation_rate',
              header: 'Degradation',
              className: 'font-telemetry',
              render: (row: StintSummary) => (
                <span
                  className={
                    row.degradation_rate > 0.1 ? 'text-safety-red' : 'text-steel'
                  }
                >
                  +{row.degradation_rate.toFixed(3)}s/lap
                </span>
              ),
            },
          ]}
          data={summary.stints}
          keyField="stint_number"
        />
      </div>

      <ChartPanel title="Race Pace" subtitle="Lap times across all stints">
        <div className="h-48 flex items-center justify-center text-steel font-telemetry text-xs">
          Pace chart — connect to live data
        </div>
      </ChartPanel>
    </div>
  );
}
