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
    async (email: string, password: string, redirectTo?: string): Promise<LoginResult | null> => {
      setLoading(true);
      setError(null);
      try {
        const result = await apiLogin(email, password);
        if (!('access_token' in result)) {
          // 2FA required — return the challenge so the login page can show the code input
          return result;
        }
        setUser(result.user);
        router.push(redirectTo ?? '/app/dashboard');
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
        setUser(result.user);
        router.push(redirectTo ?? '/app/dashboard');
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
        setUser(result.user);
        router.push(redirectTo ?? '/app/dashboard');
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
      router.push('/login');
    }
  }, [router]);

  return { user, loading, error, login, verify2fa, register, logout };
}
