'use client';

import { useState, useCallback } from 'react';
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

  // Fetch stints
  const stintsQuery = useQuery({
    queryKey: ['stints', sessionId],
    queryFn: () => api.get<StintsResponse>(`/sessions/${sessionId}/stints`),
  });

  // Fetch endurance report (only when assignments exist)
  const reportQuery = useQuery({
    queryKey: ['endurance-report', sessionId],
    queryFn: () => api.get<EnduranceReportResponse>(`/sessions/${sessionId}/endurance-report`),
    enabled: reportReady,
    retry: false,
  });

  // Check if drivers are assigned
  const stints = stintsQuery.data?.stints || [];
  const hasAssignments = stints.some((s) => s.driver_name);

  // Auto-enable report if assignments exist
  if (hasAssignments && !reportReady) {
    setReportReady(true);
  }

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

  // Loading state
  if (stintsQuery.isLoading) {
    return <SkeletonCardGrid count={4} />;
  }

  if (stintsQuery.error) {
    return <QueryError message="Failed to load stint data" />;
  }

  // No stints or no assignments → setup flow
  if (!hasAssignments || !reportReady) {
    return (
      <SetupFlow
        sessionId={sessionId}
        stints={stints}
        pitThreshold={stintsQuery.data?.pit_threshold_s || 120}
        onComplete={handleSetupComplete}
      />
    );
  }

  // Report loading
  if (reportQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        <span className="ml-3 text-steel text-sm font-body">Generating endurance report...</span>
      </div>
    );
  }

  if (reportQuery.error || !reportQuery.data) {
    return <QueryError message="Failed to generate endurance report. Make sure all stints have drivers assigned." />;
  }

  const report = reportQuery.data;

  // Tier 1: Stint Report
  if (tier === 'stint' && selectedStint != null) {
    const stintData = stints.find((s) => s.stint_number === selectedStint);
    const stintScored = report.stints[selectedStint];
    const merged: Stint = { ...(stintData || {} as Stint), ...(stintScored || {}) };
    return (
      <StintReport
        sessionId={sessionId}
        stint={merged}
        onBack={handleBack}
      />
    );
  }

  // Tier 2: Driver Report
  if (tier === 'driver' && selectedDriver) {
    const driverData = report.drivers[selectedDriver];
    if (!driverData) {
      return <QueryError message={`No data for driver: ${selectedDriver}`} />;
    }
    return (
      <DriverReport
        report={driverData}
        onSelectStint={handleSelectStint}
        onBack={handleBack}
      />
    );
  }

  // Tier 3: Team Report (default)
  return (
    <TeamReport
      report={report.team}
      stints={stints}
      onSelectDriver={handleSelectDriver}
    />
  );
}
