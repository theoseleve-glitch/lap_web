'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import type { BundleArtifactIndex } from '@/types/bundles';

export function useBundleArtifacts(bundleId: string | undefined) {
  return useQuery({
    queryKey: ['bundle-artifacts', bundleId],
    queryFn: () => api.get<BundleArtifactIndex>(`/api/v1/bundles/${bundleId}/artifacts`),
    enabled: !!bundleId,
    staleTime: 60_000,
  });
}
