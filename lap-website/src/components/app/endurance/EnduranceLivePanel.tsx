'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { QueryError } from '@/components/app';
import type { Stint, EnduranceLiveState, RaceAnchor } from './types';

interface EnduranceLivePanelProps {
  sessionId: string;
  pitThreshold: number;
  stints: Stint[];
}

function formatElapsed(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = Math.floor(totalSeconds % 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function formatLapTime(s: number | null | undefined): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export function EnduranceLivePanel({ sessionId, pitThreshold, stints }: EnduranceLivePanelProps) {
  const queryClient = useQueryClient();
  const [anchorDatetime, setAnchorDatetime] = useState('');
  const [clientElapsed, setClientElapsed] = useState(0);
  const lastServerElapsed = useRef(0);
  const lastSyncTime = useRef(Date.now());

  // Fetch live state
  const liveQuery = useQuery({
    queryKey: ['endurance-live', sessionId],
    queryFn: () => api.get<EnduranceLiveState>(`/sessions/${sessionId}/endurance-live`),
    retry: (failureCount, error) => {
      // Don't retry on 404 (no anchor yet)
      if (error && 'status' in error && (error as { status: number }).status === 404) return false;
      return failureCount < 2;
    },
    refetchInterval: (query) => {
      // Only poll when we have data (anchor exists)
      if (query.state.data) return 10_000;
      return false;
    },
  });

  // Sync client timer from server elapsed_s
  useEffect(() => {
    if (liveQuery.data) {
      lastServerElapsed.current = liveQuery.data.elapsed_s;
      lastSyncTime.current = Date.now();
      setClientElapsed(liveQuery.data.elapsed_s);
    }
  }, [liveQuery.data]);

  // Client-side timer ticking every second
  useEffect(() => {
    if (!liveQuery.data) return;
    const interval = setInterval(() => {
      const drift = (Date.now() - lastSyncTime.current) / 1000;
      setClientElapsed(lastServerElapsed.current + drift);
    }, 1000);
    return () => clearInterval(interval);
  }, [liveQuery.data]);

  // POST anchor to start tracking
  const anchorMutation = useMutation({
    mutationFn: (raceStartIso: string) =>
      api.post<RaceAnchor>(`/sessions/${sessionId}/endurance-anchor`, {
        race_start_iso: raceStartIso,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['endurance-live', sessionId] });
      liveQuery.refetch();
    },
  });

  const handleStartTracking = useCallback(() => {
    if (!anchorDatetime) return;
    const iso = new Date(anchorDatetime).toISOString();
    anchorMutation.mutate(iso);
  }, [anchorDatetime, anchorMutation]);

  // No anchor yet — show setup
  if (liveQuery.error || (!liveQuery.data && !liveQuery.isLoading)) {
    return (
      <div className="space-y-6">
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h3 className="text-lg font-monument text-chalk mb-1">Start Race Tracking</h3>
          <p className="text-steel text-xs font-body mb-4">
            Set the race start time to begin live endurance tracking.
          </p>

          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-steel text-xs font-body">Race start:</label>
            <input
              type="datetime-local"
              value={anchorDatetime}
              onChange={(e) => setAnchorDatetime(e.target.value)}
              className="px-3 py-2 bg-asphalt border border-steel/20 rounded-lg text-chalk text-sm font-telemetry"
            />
            <button
              type="button"
              onClick={handleStartTracking}
              disabled={!anchorDatetime || anchorMutation.isPending}
              className="px-4 py-2 bg-acid-green/10 border border-acid-green/30 rounded-lg text-acid-green text-sm font-body hover:bg-acid-green/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              {anchorMutation.isPending ? 'Starting...' : 'Start Race Tracking'}
            </button>
          </div>

          {anchorMutation.error && (
            <p className="text-safety-red text-xs font-body mt-3">
              {(anchorMutation.error as Error).message || 'Failed to set race anchor'}
            </p>
          )}
        </div>
      </div>
    );
  }

  // Loading
  if (liveQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        <span className="ml-3 text-steel text-sm font-body">Loading live data...</span>
      </div>
    );
  }

  const live = liveQuery.data!;
  const currentStint = live.current_stint;
  const completedStints = live.completed_stints;

  return (
    <div className="space-y-6">
      {/* Elapsed Timer */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6 text-center">
        <p className="text-steel text-xs font-body uppercase tracking-wider mb-2">Race Elapsed</p>
        <p className="text-5xl font-telemetry text-acid-green tabular-nums">
          {formatElapsed(clientElapsed)}
        </p>
        {live.next_pit_lap != null && (
          <p className="text-pit-orange text-sm font-body mt-3">
            Next pit window: Lap {live.next_pit_lap}
          </p>
        )}
      </div>

      {/* Current Stint */}
      {currentStint && (
        <div className="bg-concrete rounded-xl border border-acid-green/20 p-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-monument text-chalk">Current Stint</h3>
            <span className="inline-flex px-2 py-0.5 text-[10px] font-telemetry tracking-[0.12em] uppercase border text-acid-green bg-acid-green/10 border-acid-green/30">
              STINT {currentStint.stint_number}
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <p className="text-steel text-xs font-body mb-1">Driver</p>
              <p className="text-chalk font-body text-sm font-medium">
                {currentStint.driver_name || 'Unassigned'}
              </p>
            </div>
            <div>
              <p className="text-steel text-xs font-body mb-1">Laps</p>
              <p className="text-chalk font-telemetry text-sm">{currentStint.laps_completed}</p>
            </div>
            <div>
              <p className="text-steel text-xs font-body mb-1">Start Lap</p>
              <p className="text-chalk font-telemetry text-sm">{currentStint.start_lap}</p>
            </div>
            <div>
              <p className="text-steel text-xs font-body mb-1">Stint Time</p>
              <p className="text-chalk font-telemetry text-sm">
                {formatElapsed(currentStint.stint_elapsed_s)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Completed Stints Table */}
      {completedStints.length > 0 && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6">
          <h3 className="text-lg font-monument text-chalk mb-4">Completed Stints</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm font-body">
              <thead>
                <tr className="text-steel border-b border-steel/10 text-xs">
                  <th className="py-2 text-left">Stint</th>
                  <th className="py-2 text-left">Driver</th>
                  <th className="py-2 text-right">Laps</th>
                  <th className="py-2 text-right">Best Lap</th>
                </tr>
              </thead>
              <tbody>
                {completedStints.map((s) => (
                  <tr key={s.stint_number} className="border-b border-steel/5 text-chalk">
                    <td className="py-3 font-telemetry">{s.stint_number}</td>
                    <td className="py-3">{s.driver_name || 'Unassigned'}</td>
                    <td className="py-3 text-right font-telemetry">{s.lap_count}</td>
                    <td className="py-3 text-right font-telemetry text-acid-green">
                      {formatLapTime(s.best_lap_s)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!currentStint && completedStints.length === 0 && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-6 text-center">
          <p className="text-steel text-sm font-body">
            Race tracking is active. Waiting for stint data...
          </p>
        </div>
      )}
    </div>
  );
}
