'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import type { AuthUser } from '@/lib/auth';
import { login as apiLogin, logout as apiLogout } from '@/lib/auth';

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const login = useCallback(
    async (email: string, password: string) => {
      setLoading(true);
      setError(null);
      try {
        const result = await apiLogin(email, password);
        setUser(result.user);
        router.push('/app/dashboard');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Login failed');
      } finally {
        setLoading(false);
      }
    },
    [router],
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
      router.push('/login');
    }
  }, [router]);

  return { user, loading, error, login, logout };
}
