'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { silentRefresh, type AuthUser } from '@/lib/auth';
import { getAccessToken } from '@/lib/auth-store';
import { useTranslation } from '@/i18n';

/**
 * Wraps authenticated pages. On mount, attempts to restore the session
 * via silent refresh (httpOnly cookie). Shows a loading spinner while
 * the refresh is in flight, then either renders children or redirects
 * to /login.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useTranslation();
  const [state, setState] = useState<'loading' | 'authenticated' | 'unauthenticated'>('loading');

  useEffect(() => {
    // If we already have an access token in memory, skip the refresh
    if (getAccessToken()) {
      setState('authenticated');
      return;
    }

    // Attempt silent refresh via httpOnly cookie
    silentRefresh().then((user: AuthUser | null) => {
      if (user) {
        setState('authenticated');
      } else {
        setState('unauthenticated');
      }
    });
  }, []);

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
