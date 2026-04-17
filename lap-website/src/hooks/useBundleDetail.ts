'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import type { BundleOverview } from '@/types/bundles';

export function useBundleDetail(bundleId: string | undefined) {
  return useQuery({
    queryKey: ['bundle', bundleId],
    queryFn: () => api.get<BundleOverview>(`/api/v1/bundles/${bundleId}`),
    enabled: !!bundleId,
    staleTime: 60_000,
  });
}
