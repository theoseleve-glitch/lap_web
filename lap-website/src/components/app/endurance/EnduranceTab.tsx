'use client';

import { useState, useCallback, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { QueryError, SkeletonCardGrid } from '@/components/app';
import { SetupFlow } from './SetupFlow';
import { TeamReport } from './TeamReport';
import { DriverReport } from './DriverReport';
import { StintReport } from './StintReport';
import { EnduranceLivePanel } from './EnduranceLivePanel';
import type { StintsResponse, EnduranceReportResponse, EnduranceTier, Stint } from './types';

interface EnduranceTabProps {
  sessionId: string;
  trackName?: string | null;
  kartName?: string | null;
}

/** "Create Race Strategy from this Session" — bridges an assigned endurance
 * session into a race-strategy record (services.race_strategy_bridge on the
 * backend). Only rendered once every detected stint has a driver assigned. */
function CreateRaceLink({ sessionId, stints }: { sessionId: string; stints: Stint[] }) {
  const router = useRouter();
  const [error, setError] = useState('');

  const createRaceMut = useMutation({
    mutationFn: () => {
      const driverMap: Record<number, string> = {};
      for (const s of stints) {
        if (s.driver_name) driverMap[s.stint_number] = s.driver_name;
      }
      return api.post<{ race_id: number }>(`/sessions/${sessionId}/endurance-race`, {
        race: { race_name: `Endurance session ${sessionId.slice(0, 8)}` },
        driver_map: driverMap,
      });
    },
    onSuccess: (data) => {
      setError('');
      router.push(`/app/race-strategy/${data.race_id}`);
    },
    onError: (err: Error) => setError(err.message || 'Failed to create race'),
  });

  const allAssigned = stints.length > 0 && stints.every((s) => s.driver_name);
  if (!allAssigned) return null;

  return (
    <div className="bg-concrete rounded-xl border border-gold/20 p-4 flex items-center justify-between gap-4 flex-wrap">
      <div>
        <h3 className="font-monument text-sm text-chalk">Race Strategy</h3>
        <p className="text-steel font-body text-xs mt-1">
          Turn this session&apos;s stints and drivers into a race-strategy plan with real actual-vs-planned data.
        </p>
        {error && <p className="text-safety-red font-body text-xs mt-1">{error}</p>}
      </div>
      <button
        type="button"
        onClick={() => createRaceMut.mutate()}
        disabled={createRaceMut.isPending}
        className="px-4 py-2 bg-gold text-white font-telemetry text-xs uppercase tracking-wider rounded hover:bg-gold/80 transition-colors disabled:opacity-50 shrink-0"
      >
        {createRaceMut.isPending ? 'Creating...' : 'Create Race Strategy from this Session'}
      </button>
    </div>
  );
}

/** Small collapsible toggle for the live-tracking panel below it. */
function LiveTrackingToggle({ show, onToggle }: { show: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center gap-2 text-steel font-telemetry text-xs uppercase tracking-wider hover:text-chalk transition-colors"
    >
      {show ? '▼' : '▶'} Live Tracking
    </button>
  );
}

export function EnduranceTab({ sessionId, trackName, kartName }: EnduranceTabProps) {
  const [tier, setTier] = useState<EnduranceTier>('team');
  const [selectedDriver, setSelectedDriver] = useState<string | null>(null);
  const [selectedStint, setSelectedStint] = useState<number | null>(null);
  const [reportReady, setReportReady] = useState(false);
  const [showLive, setShowLive] = useState(false);

  // Try loading stored report from session's analysis_json
  const storedReportQuery = useQuery({
    queryKey: ['session-detail-endurance', sessionId],
    queryFn: async () => {
      const session = await api.get<{ analysis_json?: string }>(`/sessions/${sessionId}`);
      if (!session?.analysis_json) return null;
      const aj = typeof session.analysis_json === 'string'
        ? JSON.parse(session.analysis_json)
        : session.analysis_json;
      return aj?.endurance_report as EnduranceReportResponse | null;
    },
    retry: false,
  });

  // Fetch stints from DB
  const stintsQuery = useQuery({
    queryKey: ['stints', sessionId],
    queryFn: () => api.get<StintsResponse>(`/sessions/${sessionId}/stints`).catch(() => null),
    retry: false,
  });

  // Fetch live endurance report (from /endurance-report endpoint)
  const reportQuery = useQuery({
    queryKey: ['endurance-report', sessionId],
    queryFn: () => api.get<EnduranceReportResponse>(`/sessions/${sessionId}/endurance-report`).catch(() => null),
    enabled: reportReady,
    retry: false,
  });

  const stints = stintsQuery.data?.stints || [];
  const hasAssignments = stints.some((s) => s.driver_name);
  const pitThreshold = stintsQuery.data?.pit_threshold_s || 120;

  useEffect(() => {
    if (hasAssignments && !reportReady) setReportReady(true);
  }, [hasAssignments, reportReady]);

  // Use stored report (from analysis_json) OR live report
  const report: EnduranceReportResponse | null = storedReportQuery.data || reportQuery.data || null;

  const handleSetupComplete = useCallback(() => {
    setReportReady(true);
    stintsQuery.refetch();
  }, [stintsQuery]);

  const handleSelectDriver = useCallback((name: string) => {
    setSelectedDriver(name);
    setTier('driver');
  }, []);

  const handleSelectStint = useCallback((stintNumber: number) => {
    setSelectedStint(stintNumber);
    setTier('stint');
  }, []);

  const handleBack = useCallback(() => {
    if (tier === 'stint') {
      setTier('driver');
      setSelectedStint(null);
    } else if (tier === 'driver') {
      setTier('team');
      setSelectedDriver(null);
    }
  }, [tier]);

  // Loading
  if (storedReportQuery.isLoading) {
    return <SkeletonCardGrid count={4} />;
  }

  // If we have a stored report, show it directly (skip setup flow)
  if (report) {
    const reportStints: Stint[] = (report as any).stint_results?.map((sr: any) => ({
      stint_number: sr.stint_number,
      start_lap: sr.start_lap,
      end_lap: sr.end_lap,
      lap_count: sr.lap_count,
      driver_name: sr.driver_name,
      condition: sr.condition,
      pit_lap_number: sr.pit_lap_number ?? null,
      pit_lap_time_s: sr.pit_lap_time_s ?? null,
      pit_duration_s: sr.pit_duration_s ?? null,
      best_lap_s: sr.best_lap_s,
      mean_lap_s: sr.mean_lap_s,
    })) || stints;

    // Tier 1: Stint — merge stint config + stint result data
    if (tier === 'stint' && selectedStint != null) {
      const stintFromList = reportStints.find((s) => s.stint_number === selectedStint);
      const stintResult = (report as any).stint_results?.find((sr: any) => sr.stint_number === selectedStint);
      const merged = { ...(stintFromList || {}), ...(stintResult || {}) } as Stint;
      return <StintReport sessionId={sessionId} stint={merged} onBack={handleBack} trackName={trackName} kartName={kartName} />;
    }

    // Tier 2: Driver
    if (tier === 'driver' && selectedDriver) {
      const driverData = report.drivers?.[selectedDriver];
      if (!driverData) return <QueryError message={`No data for driver: ${selectedDriver}`} />;
      return <DriverReport report={driverData} onSelectStint={handleSelectStint} onBack={handleBack} />;
    }

    // Tier 3: Team (default)
    return (
      <div className="space-y-4">
        <CreateRaceLink sessionId={sessionId} stints={reportStints} />
        <LiveTrackingToggle show={showLive} onToggle={() => setShowLive((v) => !v)} />
        {showLive && (
          <EnduranceLivePanel sessionId={sessionId} pitThreshold={pitThreshold} stints={reportStints} />
        )}
        <TeamReport
          report={report.team}
          stints={reportStints}
          pitThreshold={(report.team as any).pit_threshold_s || stintsQuery.data?.pit_threshold_s || 30}
          onSelectDriver={handleSelectDriver}
        />
      </div>
    );
  }

  // No stored report — show setup flow or loading
  if (stintsQuery.isLoading) return <SkeletonCardGrid count={4} />;

  return (
    <div className="space-y-4">
      <CreateRaceLink sessionId={sessionId} stints={stints} />
      <LiveTrackingToggle show={showLive} onToggle={() => setShowLive((v) => !v)} />
      {showLive && (
        <EnduranceLivePanel sessionId={sessionId} pitThreshold={pitThreshold} stints={stints} />
      )}
      <SetupFlow
        sessionId={sessionId}
        stints={stints}
        pitThreshold={pitThreshold}
        onComplete={handleSetupComplete}
      />
    </div>
  );
}
