'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import type { AnalyzeResponse } from '@/types/bundles';

export function useTriggerAnalysis(bundleId: string) {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: (forceRerun: boolean = false) =>
      api.post<AnalyzeResponse>(`/api/v1/bundles/${bundleId}/analyze`, {
        force_rerun: forceRerun,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bundle-run', bundleId] });
    },
  });
}
