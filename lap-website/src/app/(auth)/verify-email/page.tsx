'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { verifyEmail } from '@/lib/auth';
import { useTranslation } from '@/i18n';

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token');
  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [error, setError] = useState<string | null>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setError(t('auth.verifyEmail.noToken'));
      return;
    }

    verifyEmail(token)
      .then(() => setStatus('success'))
      .catch((err) => {
        setStatus('error');
        setError(err instanceof Error ? err.message : t('auth.verifyEmail.fallbackError'));
      });
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {status === 'verifying' && (
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
          <p className="text-steel font-body">{t('auth.verifyEmail.verifying')}</p>
        </div>
      )}

      {status === 'success' && (
        <div>
          <p className="text-acid-green font-body mb-4">{t('auth.verifyEmail.success')}</p>
          <Link
            href="/login"
            className="inline-block py-2 px-6 bg-pit-orange text-white font-monument text-lg rounded hover:brightness-110 transition-all"
          >
            {t('auth.verifyEmail.signIn')}
          </Link>
        </div>
      )}

      {status === 'error' && (
        <div>
          <p className="text-safety-red font-body mb-4">{error || t('auth.verifyEmail.fallbackError')}</p>
          <Link href="/login" className="text-pit-orange hover:underline font-body">
            {t('auth.verifyEmail.backToLogin')}
          </Link>
        </div>
      )}
    </>
  );
}

export default function VerifyEmailPage() {
  const { t } = useTranslation();

  return (
    <div className="text-center">
      <h1 className="font-monument text-2xl text-chalk mb-6">{t('auth.verifyEmail.title')}</h1>
      <Suspense
        fallback={
          <div className="flex flex-col items-center gap-4">
            <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
            <p className="text-steel font-body">{t('auth.verifyEmail.loading')}</p>
          </div>
        }
      >
        <VerifyEmailContent />
      </Suspense>
    </div>
  );
}
