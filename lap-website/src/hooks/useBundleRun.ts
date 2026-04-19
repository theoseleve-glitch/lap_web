'use client';

import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api-client';
import type { AnalysisRunSummary, RunDisplayState } from '@/types/bundles';
import { getSupportLevel } from '@/lib/bundle-vocabulary';

export function useBundleRun(bundleId: string | undefined) {
  const query = useQuery({
    queryKey: ['bundle-run', bundleId],
    queryFn: async () => {
      try {
        return await api.get<AnalysisRunSummary>(`/api/v1/bundles/${bundleId}/runs/latest`);
      } catch (err) {
        if (err instanceof ApiError && err.code === 'NOT_FOUND') return null;
        throw err;
      }
    },
    enabled: !!bundleId,
    staleTime: 0,
    refetchInterval: (query) => {
      const run = query.state.data;
      if (!run) return false;
      if (run.status === 'queued' || run.status === 'running') return 3_000;
      return false;
    },
  });

  const displayState = deriveDisplayState(query.data);

  return { ...query, displayState };
}

function deriveDisplayState(run: AnalysisRunSummary | null | undefined): RunDisplayState {
  if (!run) return { phase: 'no-run' };
  if (run.status === 'queued') return { phase: 'queued' };
  if (run.status === 'running') return { phase: 'running' };
  if (run.status === 'failed') {
    return { phase: 'failed', errorMessage: run.support_reason ?? 'Analysis failed', run };
  }
  return {
    phase: 'succeeded',
    tier: getSupportLevel(run.support_tier),
    run,
  };
}
