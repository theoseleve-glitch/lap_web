'use client';

import { useState, useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { QueryError, SkeletonCardGrid } from '@/components/app';
import { SetupFlow } from './SetupFlow';
import { TeamReport } from './TeamReport';
import { DriverReport } from './DriverReport';
import { StintReport } from './StintReport';
import type { StintsResponse, EnduranceReportResponse, EnduranceTier, Stint } from './types';

interface EnduranceTabProps {
  sessionId: string;
}

export function EnduranceTab({ sessionId }: EnduranceTabProps) {
  const [tier, setTier] = useState<EnduranceTier>('team');
  const [selectedDriver, setSelectedDriver] = useState<string | null>(null);
  const [selectedStint, setSelectedStint] = useState<number | null>(null);
  const [reportReady, setReportReady] = useState(false);

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

    // Tier 1: Stint
    if (tier === 'stint' && selectedStint != null) {
      const stintData = reportStints.find((s) => s.stint_number === selectedStint);
      return <StintReport sessionId={sessionId} stint={stintData || {} as Stint} onBack={handleBack} />;
    }

    // Tier 2: Driver
    if (tier === 'driver' && selectedDriver) {
      const driverData = report.drivers?.[selectedDriver];
      if (!driverData) return <QueryError message={`No data for driver: ${selectedDriver}`} />;
      return <DriverReport report={driverData} onSelectStint={handleSelectStint} onBack={handleBack} />;
    }

    // Tier 3: Team (default)
    return (
      <TeamReport
        report={report.team}
        stints={reportStints}
        pitThreshold={stintsQuery.data?.pit_threshold_s || 30}
        onSelectDriver={handleSelectDriver}
      />
    );
  }

  // No stored report — show setup flow or loading
  if (stintsQuery.isLoading) return <SkeletonCardGrid count={4} />;

  const pitThreshold = stintsQuery.data?.pit_threshold_s || 120;

  return (
    <SetupFlow
      sessionId={sessionId}
      stints={stints}
      pitThreshold={pitThreshold}
      onComplete={handleSetupComplete}
    />
  );
}
