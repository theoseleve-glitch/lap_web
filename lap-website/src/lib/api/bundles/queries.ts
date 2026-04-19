/**
 * TanStack Query hooks for bundle/session analysis.
 *
 * No endpoint calls from view components — all data flows through here.
 */
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api-client';
import { bundleKeys } from './keys';
import type {
  AnalysisRunDTO,
  AnalyzeResponseDTO,
  BundleArtifactIndexDTO,
  BundleListDTO,
  BundleOverviewDTO,
} from './types';

// ── Bundle list ───────────────────────────────────────────

export function useBundleList(limit = 25) {
  return useQuery({
    queryKey: bundleKeys.list(),
    queryFn: () => api.get<BundleListDTO>(`/api/v1/bundles?limit=${limit}`),
    staleTime: 30_000,
  });
}

// ── Bundle detail ─────────────────────────────────────────

export function useBundleDetail(bundleId: string | undefined) {
  return useQuery({
    queryKey: bundleKeys.detail(bundleId!),
    queryFn: () => api.get<BundleOverviewDTO>(`/api/v1/bundles/${bundleId}`),
    enabled: !!bundleId,
    staleTime: 60_000,
  });
}

// ── Latest run ────────────────────────────────────────────

export function useBundleRun(bundleId: string | undefined) {
  return useQuery({
    queryKey: bundleKeys.run(bundleId!),
    queryFn: async (): Promise<AnalysisRunDTO | null> => {
      try {
        return await api.get<AnalysisRunDTO>(`/api/v1/bundles/${bundleId}/runs/latest`);
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
}

// ── Artifacts ─────────────────────────────────────────────

export function useBundleArtifacts(bundleId: string | undefined) {
  return useQuery({
    queryKey: bundleKeys.artifacts(bundleId!),
    queryFn: () => api.get<BundleArtifactIndexDTO>(`/api/v1/bundles/${bundleId}/artifacts`),
    enabled: !!bundleId,
    staleTime: 60_000,
  });
}

// ── Trigger analysis ──────────────────────────────────────

export function useTriggerAnalysis(bundleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (forceRerun = false) =>
      api.post<AnalyzeResponseDTO>(`/api/v1/bundles/${bundleId}/analyze`, {
        force_rerun: forceRerun,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: bundleKeys.run(bundleId) });
    },
  });
}
