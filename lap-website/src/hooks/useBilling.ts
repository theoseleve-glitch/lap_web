'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api-client';

export interface BillingStatus {
  plan_tier: string;
  subscription_status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  payment_method: { brand: string; last4: string } | null;
  next_invoice_amount: number | null;
  next_invoice_currency: string | null;
}

export function useBilling() {
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchBilling = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.get<BillingStatus>('/billing/subscription');
      setBilling(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load billing status');
    } finally {
      setLoading(false);
    }
  }, []);

  const openPortal = useCallback(async () => {
    const data = await api.post<{ portal_url: string }>('/billing/portal', {});
    window.location.href = data.portal_url;
  }, []);

  useEffect(() => {
    fetchBilling();
  }, [fetchBilling]);

  return { billing, loading, error, openPortal, refetch: fetchBilling };
}
