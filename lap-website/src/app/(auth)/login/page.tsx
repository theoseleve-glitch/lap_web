'use client';

import { useState, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormField } from '@/components/app/FormField';
import { useAuth } from '@/hooks/useAuth';
import { OAuthButtons } from '@/components/auth/OAuthButtons';
import { useTranslation } from '@/i18n';

function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const searchParams = useSearchParams();
  const redirect = searchParams.get('redirect') ?? '/app/dashboard';
  const oauthError = searchParams.get('error');
  const { login, loading, error } = useAuth();
  const { t } = useTranslation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await login(email, password, redirect);
  };

  const displayError = error ?? (oauthError ? `${t('auth.login.oauthError')} ${oauthError.replace(/_/g, ' ')}` : null);

  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-6 text-center">{t('auth.login.title')}</h1>

      {displayError && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{displayError}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <FormField
          label={t('auth.login.email')}
          type="email"
          placeholder={t('auth.login.emailPlaceholder')}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />
        <FormField
          label={t('auth.login.password')}
          type="password"
          placeholder={t('auth.login.passwordPlaceholder')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
        />

        <button
          type="submit"
          disabled={loading}
          className="w-full mt-2 py-3 bg-pit-orange text-asphalt font-monument text-lg tracking-wider
            rounded hover:brightness-110 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? t('auth.login.submitting') : t('auth.login.submit')}
        </button>
      </form>

      <OAuthButtons />

      <div className="mt-6 text-center">
        <p className="text-steel font-body text-sm">
          {t('auth.login.noAccount')}{' '}
          <Link href="/register" className="text-pit-orange hover:underline">
            {t('auth.login.createOne')}
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
