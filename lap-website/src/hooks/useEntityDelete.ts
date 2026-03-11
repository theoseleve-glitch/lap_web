'use client';

import { useState, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';

export interface EntityDeleteConfig {
  /** Entity type label for logging */
  entity: string;
  /** Entity ID */
  id: string | number;
  /** API endpoint path, e.g. '/drivers/42' */
  endpoint: string;
  /** Query keys to invalidate on success, e.g. [['drivers'], ['sessions']] */
  invalidate: string[][];
  /** Redirect path after delete on detail pages */
  redirectTo?: string;
  /** Extra callback after successful delete */
  onSuccess?: () => void;
}

export interface EntityDeleteResult {
  showConfirm: boolean;
  isPending: boolean;
  error: string | null;
  impact: Record<string, number> | null;
  isLoadingImpact: boolean;
  requestDelete: () => void;
  confirmDelete: () => void;
  cancelDelete: () => void;
}

export function useEntityDelete(config: EntityDeleteConfig): EntityDeleteResult {
  const { entity, id, endpoint, invalidate, redirectTo, onSuccess } = config;
  const queryClient = useQueryClient();
  const router = useRouter();

  const [showConfirm, setShowConfirm] = useState(false);
  const [impact, setImpact] = useState<Record<string, number> | null>(null);
  const [isLoadingImpact, setIsLoadingImpact] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: () => api.delete<{ deleted: boolean; impact: Record<string, number> }>(endpoint),
    onSuccess: () => {
      // Invalidate all related query keys
      for (const key of invalidate) {
        queryClient.invalidateQueries({ queryKey: key });
      }
      setShowConfirm(false);
      setError(null);
      onSuccess?.();
      if (redirectTo) {
        router.push(redirectTo);
      }
    },
    onError: (err: Error) => {
      setError(err.message || 'Delete failed');
    },
  });

  const requestDelete = useCallback(() => {
    setShowConfirm(true);
    setError(null);
    setIsLoadingImpact(true);
    setImpact(null);

    // Fetch impact preview
    api.get<{ impact: Record<string, number> }>(`${endpoint}/delete-impact`)
      .then((data) => {
        setImpact(data.impact);
      })
      .catch(() => {
        // Non-critical — panel still works without impact data
        setImpact(null);
      })
      .finally(() => {
        setIsLoadingImpact(false);
      });
  }, [endpoint]);

  const confirmDelete = useCallback(() => {
    setError(null);
    deleteMutation.mutate();
  }, [deleteMutation]);

  const cancelDelete = useCallback(() => {
    setShowConfirm(false);
    setImpact(null);
    setError(null);
  }, []);

  return {
    showConfirm,
    isPending: deleteMutation.isPending,
    error,
    impact,
    isLoadingImpact,
    requestDelete,
    confirmDelete,
    cancelDelete,
  };
}
