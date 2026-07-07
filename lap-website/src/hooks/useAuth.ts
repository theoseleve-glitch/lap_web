'use client';

import { useState, useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import type { AuthUser, LoginResult } from '@/lib/auth';
import {
  login as apiLogin,
  verify2fa as apiVerify2fa,
  register as apiRegister,
  logout as apiLogout,
  silentRefresh,
} from '@/lib/auth';
import { queryClient } from '@/providers/query-provider';
import { getSafeRedirect } from '@/lib/safe-redirect';

/** Clear React Query cache — safe to call even outside QueryClientProvider. */
function clearQueryCache(): void {
  queryClient?.clear();
}

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  // On mount: attempt silent refresh to restore session from httpOnly cookie
  useEffect(() => {
    let cancelled = false;
    silentRefresh().then((restored) => {
      if (!cancelled) {
        setUser(restored);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);

  const login = useCallback(
    async (
      email: string,
      password: string,
      redirectTo?: string,
      turnstileToken?: string,
    ): Promise<LoginResult | null> => {
      setLoading(true);
      setError(null);
      try {
        const result = await apiLogin(email, password, turnstileToken);
        if (!('access_token' in result)) {
          return result;
        }
        clearQueryCache();
        setUser(result.user);
        router.push(getSafeRedirect(redirectTo, '/app/dashboard'));
        return result;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Login failed');
        return null;
      } finally {
        setLoading(false);
      }
    },
    [router],
  );

  const verify2fa = useCallback(
    async (tempToken: string, code: string, isBackup: boolean, redirectTo?: string) => {
      setLoading(true);
      setError(null);
      try {
        const result = await apiVerify2fa(tempToken, code, isBackup);
        clearQueryCache();
        setUser(result.user);
        router.push(getSafeRedirect(redirectTo, '/app/dashboard'));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Verification failed');
      } finally {
        setLoading(false);
      }
    },
    [router],
  );

  const register = useCallback(
    async (email: string, password: string, displayName: string, redirectTo?: string) => {
      setLoading(true);
      setError(null);
      try {
        const result = await apiRegister(email, password, displayName);
        clearQueryCache();
        setUser(result.user);
        router.push(getSafeRedirect(redirectTo, '/app/dashboard'));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Registration failed');
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
      clearQueryCache();
      router.push('/login');
    }
  }, [router]);

  return { user, loading, error, login, verify2fa, register, logout };
}
