'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api-client';

export interface UsageMetric {
  metric: string;
  used: number;
  limit: number | null;
  unit: string;
}

export interface UsageSnapshot {
  period_start: string;
  period_end: string;
  metrics: UsageMetric[];
  storage_used_mb: number;
  storage_limit_mb: number | null;
}

export function useUsage() {
  const [usage, setUsage] = useState<UsageSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchUsage = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.get<UsageSnapshot>('/account/usage');
      setUsage(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsage();
  }, [fetchUsage]);

  return { usage, loading, error, refetch: fetchUsage };
}
