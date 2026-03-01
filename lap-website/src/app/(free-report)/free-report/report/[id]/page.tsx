'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api-client';
import { StatCard, DataTable, LockedSection, UpgradeBanner } from '@/components/app';
import { SpeedTrace, TrackMap, GGDiagram, DrivingStyle } from '@/components/app/charts';
import { CornerReplay } from '@/components/app/corner-replay';

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

interface CornerSummary {
  corner_id: number;
  corner_name: string;
  time_loss: number;
}

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export default function FreeReportPage() {
  const { id } = useParams<{ id: string }>();

  const { data: session, isLoading } = useQuery({
    queryKey: ['session', id],
    queryFn: () => api.get<SessionDetail>(`/sessions/${id}/details`),
  });

  const { data: lapsData } = useQuery({
    queryKey: ['session', id, 'laps'],
    queryFn: () => api.get<{ laps: LapRow[] }>(`/sessions/${id}/laps`),
  });

  const { data: cornersData } = useQuery({
    queryKey: ['session', id, 'corners'],
    queryFn: () => api.get<{ corners: CornerSummary[] }>(`/sessions/${id}/corners`),
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
  const corners = cornersData?.corners ?? [];
  const worstCorner = [...corners].sort((a, b) => b.time_loss - a.time_loss)[0];
  const previewLaps = laps.slice(0, 3);

  const lapColumns = [
    { key: 'lap_number', header: 'Lap', sortable: true, className: 'font-telemetry w-16' },
    {
      key: 'time',
      header: 'Time',
      sortable: true,
      className: 'font-telemetry',
      render: (row: LapRow) => <span className="text-acid-green">{formatTime(row.time)}</span>,
    },
    {
      key: 'speed_avg',
      header: 'Avg Speed',
      className: 'font-telemetry',
      render: (row: LapRow) => (
        <span>{row.speed_avg != null ? `${row.speed_avg.toFixed(1)} km/h` : '--'}</span>
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
      {/* Header */}
      <div className="mb-6">
        <h1 className="font-monument text-3xl text-chalk tracking-tight">
          {session.track_name}
        </h1>
        <p className="text-steel font-body mt-1">
          {session.driver_name} -- {session.date} -- {session.laps} laps
        </p>
      </div>

      <UpgradeBanner />

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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Pace" value={session.pace_score?.toFixed(1) ?? '--'} unit="/25" />
        <StatCard label="Consistency" value={session.consistency_score?.toFixed(1) ?? '--'} unit="/25" />
        <StatCard label="Execution" value={session.execution_score?.toFixed(1) ?? '--'} unit="/25" />
        <StatCard label="Robustness" value={session.robustness_score?.toFixed(1) ?? '--'} unit="/25" />
      </div>

      {/* FREE: Track Map + Speed Trace */}
      <div className="mb-6">
        <h2 className="font-monument text-lg text-chalk tracking-tight mb-4">ANALYSIS</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <TrackMap sessionId={id} />
          <SpeedTrace sessionId={id} />
        </div>
      </div>

      {/* LOCKED: Full Overview */}
      <div className="mb-6">
        <LockedSection title="Full Overview" description="GG diagram, driving style analysis, and more">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <GGDiagram sessionId={id} />
            <DrivingStyle sessionId={id} />
          </div>
        </LockedSection>
      </div>

      {/* FREE: Top 1 Corner Coaching */}
      {worstCorner && (
        <div className="mb-6">
          <h2 className="font-monument text-lg text-chalk tracking-tight mb-4">KEY CORNER</h2>
          <p className="text-steel font-body text-sm mb-3">
            Your biggest time loss: {worstCorner.corner_name} ({worstCorner.time_loss.toFixed(3)}s)
          </p>
          <div className="h-[400px] bg-concrete rounded-lg border border-steel/20 overflow-hidden">
            <CornerReplay sessionId={id} />
          </div>
        </div>
      )}

      {/* LOCKED: Remaining Corners */}
      {corners.length > 1 && (
        <div className="mb-6">
          <LockedSection
            title={`All ${corners.length} Corners`}
            description="See detailed coaching for every corner on the circuit"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4">
              {corners.slice(1, 4).map((c) => (
                <div key={c.corner_id} className="bg-asphalt rounded-lg p-4 border border-steel/20">
                  <p className="font-monument text-sm text-chalk">{c.corner_name}</p>
                  <p className="text-steel font-telemetry text-xs mt-1">
                    Time loss: {c.time_loss.toFixed(3)}s
                  </p>
                </div>
              ))}
            </div>
          </LockedSection>
        </div>
      )}

      {/* LOCKED: Pace Analysis */}
      <div className="mb-6">
        <LockedSection title="Pace Analysis" description="Lap-by-lap progression, sector times, and distribution">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-48">
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
          </div>
        </LockedSection>
      </div>

      {/* LOCKED: Style Analysis */}
      <div className="mb-6">
        <LockedSection title="Style Analysis" description="Fingerprint, consistency heatmap, and brake analysis">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-48">
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
          </div>
        </LockedSection>
      </div>

      {/* LOCKED: Physics Analysis */}
      <div className="mb-6">
        <LockedSection title="Physics Analysis" description="Energy balance, fatigue, speed profile, and throttle map">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-48">
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
            <div className="bg-asphalt rounded-lg border border-steel/10 p-4" />
          </div>
        </LockedSection>
      </div>

      {/* Lap Data: first 3 visible, rest locked */}
      {laps.length > 0 && (
        <div className="mb-6">
          <h2 className="font-monument text-lg text-chalk tracking-tight mb-3">LAP TIMES</h2>
          <DataTable columns={lapColumns} data={previewLaps} keyField="lap_number" />

          {laps.length > 3 && (
            <div className="mt-2">
              <LockedSection
                title="Full Lap Data"
                description={`See all ${laps.length} laps with detailed timing`}
              >
                <div className="h-24 bg-asphalt rounded-lg border border-steel/10" />
              </LockedSection>
            </div>
          )}
        </div>
      )}

      {/* Bottom upgrade CTA */}
      <div className="text-center py-8 border-t border-steel/20 mt-8">
        <p className="font-monument text-xl text-chalk mb-2">WANT THE FULL PICTURE?</p>
        <p className="text-steel font-body mb-6">
          Upgrade to Performance for unlimited sessions, all corners, and every analysis tab.
        </p>
        <a
          href="/pricing"
          className="inline-block px-8 py-3 bg-pit-orange text-asphalt font-monument text-lg tracking-wider rounded hover:brightness-110 transition-all"
        >
          Upgrade to Racer — from €5.75/mo
        </a>
      </div>
    </div>
  );
}
