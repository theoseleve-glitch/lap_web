'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, DataTable } from '@/components/app';
import {
  SpeedTrace,
  GGDiagram,
  TrackMap,
  DrivingStyle,
  LapProgress,
  SectorChart,
  LapDistribution,
  LapOverlay,
  Fingerprint,
  ConsistencyHeatmap,
  BrakeScatter,
  CornerMastery,
  EnergyBalance,
  FatigueChart,
  SpeedProfile,
  ThrottleHeatmap,
} from '@/components/app/charts';

interface SessionDetail {
  id: string;
  date: string;
  track_name: string;
  driver_name: string;
  laps: number;
  best_time: number | null;
  score: number | null;
  grade: string | null;
  consistency_score: number | null;
  pace_score: number | null;
  execution_score: number | null;
  robustness_score: number | null;
}

interface LapRow {
  lap_number: number;
  time: number;
  speed_avg: number | null;
  valid: boolean;
}

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

const tabs = ['Overview', 'Pace', 'Style', 'Physics'] as const;
type Tab = (typeof tabs)[number];

export default function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<Tab>('Overview');

  const { data: session, isLoading } = useQuery({
    queryKey: ['session', id],
    queryFn: () => api.get<SessionDetail>(`/sessions/${id}/details`),
  });

  const { data: lapsData } = useQuery({
    queryKey: ['session', id, 'laps'],
    queryFn: () => api.get<{ laps: LapRow[] }>(`/sessions/${id}/laps`),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) {
    return <div className="text-steel font-body">Session not found</div>;
  }

  const laps = lapsData?.laps ?? [];

  const lapColumns = [
    {
      key: 'lap_number',
      header: 'Lap',
      sortable: true,
      className: 'font-telemetry w-16',
    },
    {
      key: 'time',
      header: 'Time',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className="text-acid-green">{formatTime(row.time)}</span>
      ),
    },
    {
      key: 'speed_avg',
      header: 'Avg Speed',
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span>
          {row.speed_avg != null ? `${row.speed_avg.toFixed(1)} km/h` : '--'}
        </span>
      ),
    },
    {
      key: 'valid',
      header: 'Valid',
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span className={row.valid ? 'text-acid-green' : 'text-safety-red'}>
          {row.valid ? 'Y' : 'N'}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title={session.track_name}
        subtitle={`${session.driver_name} -- ${session.date} -- ${session.laps} laps`}
      />

      {/* Primary score cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard label="Best Time" value={formatTime(session.best_time)} trend="neutral" />
        <StatCard label="Total Laps" value={session.laps} />
        <StatCard
          label="Score"
          value={session.score?.toFixed(1) ?? '--'}
          unit="/100"
          trend={session.score != null && session.score >= 75 ? 'up' : 'neutral'}
        />
        <StatCard label="Grade" value={session.grade ?? '--'} />
      </div>

      {/* Score breakdown */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Pace" value={session.pace_score?.toFixed(1) ?? '--'} unit="/25" />
        <StatCard
          label="Consistency"
          value={session.consistency_score?.toFixed(1) ?? '--'}
          unit="/25"
        />
        <StatCard
          label="Execution"
          value={session.execution_score?.toFixed(1) ?? '--'}
          unit="/25"
        />
        <StatCard
          label="Robustness"
          value={session.robustness_score?.toFixed(1) ?? '--'}
          unit="/25"
        />
      </div>

      {/* Chart tabs */}
      <div className="mb-6">
        <div className="flex gap-1 border-b border-steel/20 mb-4">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 font-telemetry text-sm transition-colors ${
                activeTab === tab
                  ? 'text-acid-green border-b-2 border-acid-green'
                  : 'text-steel hover:text-chalk'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {activeTab === 'Overview' && (
            <>
              <SpeedTrace sessionId={id} />
              <GGDiagram sessionId={id} />
              <TrackMap sessionId={id} />
              <DrivingStyle sessionId={id} />
            </>
          )}
          {activeTab === 'Pace' && (
            <>
              <LapProgress sessionId={id} />
              <SectorChart sessionId={id} />
              <LapDistribution sessionId={id} />
              <LapOverlay sessionId={id} />
            </>
          )}
          {activeTab === 'Style' && (
            <>
              <Fingerprint sessionId={id} />
              <ConsistencyHeatmap sessionId={id} />
              <BrakeScatter sessionId={id} />
              <CornerMastery sessionId={id} />
            </>
          )}
          {activeTab === 'Physics' && (
            <>
              <EnergyBalance sessionId={id} />
              <FatigueChart sessionId={id} />
              <SpeedProfile sessionId={id} />
              <ThrottleHeatmap sessionId={id} />
            </>
          )}
        </div>
      </div>

      {/* Lap table */}
      {laps.length > 0 && (
        <div>
          <h2 className="font-body text-chalk text-lg mb-3">Lap Times</h2>
          <DataTable
            columns={lapColumns}
            data={laps}
            keyField="lap_number"
          />
        </div>
      )}
    </div>
  );
}
