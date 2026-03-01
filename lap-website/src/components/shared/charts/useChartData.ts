/**
 * useChartData.ts — Shared data-fetching hook for chart components.
 *
 * Handles the dual-mode pattern: if `data` prop is provided, use it directly;
 * if `sessionId` is provided, fetch from the API.
 *
 * Returns { data, loading, error }.
 */
'use client';

import { useState, useEffect, useRef } from 'react';
import { apiFetch, ApiError } from '@/lib/api-client';

interface UseChartDataOptions<T> {
  /** Pre-fetched data — if provided, skip API fetch */
  data?: T;
  /** Session ID for API fetch */
  sessionId?: string;
  /** API path relative to session (e.g. 'gps-trace?lap=1') */
  endpoint?: string;
  /** Transform API response data before returning */
  transform?: (raw: Record<string, unknown>) => T;
}

interface UseChartDataResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useChartData<T>(options: UseChartDataOptions<T>): UseChartDataResult<T> {
  const { data: preFetched, sessionId, endpoint, transform } = options;
  const [data, setData] = useState<T | null>(preFetched ?? null);
  const [loading, setLoading] = useState(!preFetched && !!sessionId);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (preFetched) {
      setData(preFetched);
      setLoading(false);
      setError(null);
      return;
    }

    if (!sessionId || !endpoint) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        // apiFetch unwraps the envelope — returns data directly
        const result = await apiFetch<Record<string, unknown>>(
          `/sessions/${sessionId}/${endpoint}`,
        );
        if (cancelled || !mountedRef.current) return;
        const transformed = transform ? transform(result) : (result as unknown as T);
        setData(transformed);
        setLoading(false);
      } catch (err) {
        if (cancelled || !mountedRef.current) return;
        const message = err instanceof ApiError
          ? err.message
          : err instanceof Error ? err.message : 'Fetch failed';
        setError(message);
        setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [preFetched, sessionId, endpoint, transform]);

  return { data, loading, error };
}
