'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api-client';

export interface AccountProfile {
  id: number;
  email: string;
  display_name: string;
  avatar_url: string | null;
  email_verified: boolean;
  plan_tier: string;
  subscription_status: string | null;
  preferences: {
    language?: string;
    timezone?: string;
    units?: 'metric' | 'imperial';
    notifications?: {
      report_ready?: boolean;
      billing_alerts?: boolean;
      product_updates?: boolean;
      weekly_digest?: boolean;
    };
  };
}

export function useAccount() {
  const [profile, setProfile] = useState<AccountProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProfile = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.get<AccountProfile>('/me');
      setProfile(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load profile');
    } finally {
      setLoading(false);
    }
  }, []);

  const updateProfile = useCallback(
    async (
      updates: Partial<
        Pick<AccountProfile, 'display_name' | 'email' | 'avatar_url' | 'preferences'>
      >,
    ) => {
      const data = await api.put<AccountProfile>('/account/profile', updates);
      setProfile(data);
      return data;
    },
    [],
  );

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  return { profile, loading, error, updateProfile, refetch: fetchProfile };
}
