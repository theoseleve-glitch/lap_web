'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { silentRefresh, type AuthUser } from '@/lib/auth';
import { getAccessToken, getUserProfile, setUserProfile } from '@/lib/auth-store';
import { useTranslation } from '@/i18n';

const ONBOARDING_PATH = '/app/onboarding';
const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';

/**
 * Wraps authenticated pages. On mount, attempts to restore the session
 * via silent refresh (httpOnly cookie). Shows a loading spinner while
 * the refresh is in flight, then either renders children or redirects
 * to /login.
 *
 * Also enforces profile completeness: if the user's display_name is
 * empty, they are redirected to /app/onboarding before accessing any
 * other app page.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useTranslation();
  const [state, setState] = useState<'loading' | 'authenticated' | 'unauthenticated'>('loading');

  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      let user: AuthUser | null = getUserProfile();

      if (getAccessToken() && user) {
        // Fast path: token + profile already in memory
      } else if (getAccessToken()) {
        // Token present (e.g. from BroadcastChannel) but no cached profile
        try {
          const res = await fetch(`${BACKEND_URL}/api/v1/me`, {
            headers: {
              Authorization: `Bearer ${getAccessToken()}`,
              'Content-Type': 'application/json',
            },
            credentials: 'include',
          });
          if (res.ok) {
            const envelope = await res.json();
            if (envelope?.data) {
              user = {
                id: envelope.data.id,
                email: envelope.data.email,
                display_name: envelope.data.display_name ?? '',
              };
              setUserProfile(user);
            }
          }
        } catch {
          // Non-fatal — skip profile check
        }
      } else {
        // No token — try silent refresh (also stores profile via auth.ts)
        user = await silentRefresh();
      }

      if (cancelled) return;

      // No valid session
      if (!user && !getAccessToken()) {
        setState('unauthenticated');
        return;
      }

      // Profile completeness gate: redirect if display_name is empty
      if (user && !user.display_name?.trim() && pathname !== ONBOARDING_PATH) {
        router.replace(ONBOARDING_PATH);
        return;
      }

      setState('authenticated');
    }

    checkAuth();

    return () => { cancelled = true; };
  }, [pathname, router]);

  if (state === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-asphalt">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-steel/30 border-t-acid-green" />
          <p className="font-body text-sm text-steel">{t('auth.guard.restoring')}</p>
        </div>
      </div>
    );
  }

  if (state === 'unauthenticated') {
    const redirectTo = encodeURIComponent(pathname);
    router.replace(`/login?redirect=${redirectTo}`);
    return null;
  }

  return <>{children}</>;
}
