'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { setAccessToken } from '@/lib/auth-store';
import { silentRefresh } from '@/lib/auth';
import { useTranslation } from '@/i18n';

export default function OAuthCallbackPage() {
  const router = useRouter();
  const { t } = useTranslation();

  useEffect(() => {
    const hash = window.location.hash;
    const params = new URLSearchParams(hash.substring(1));
    const token = params.get('access_token');

    if (token) {
      setAccessToken(token);
      // Clear hash from URL (token should not linger in browser history)
      window.history.replaceState(null, '', window.location.pathname);
      router.push('/app/dashboard');
    } else {
      // Fallback: try silent refresh via httpOnly cookie
      silentRefresh().then((user) => {
        if (user) {
          router.push('/app/dashboard');
        } else {
          router.push('/login?error=oauth_failed');
        }
      });
    }
  }, [router]);

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      <p className="text-steel font-body">{t('auth.oauthCallback.completing')}</p>
    </div>
  );
}
