'use client';

import { useState } from 'react';
import Link from 'next/link';
import { FormField } from '@/components/app/FormField';
import { forgotPassword } from '@/lib/auth';
import { useTranslation } from '@/i18n';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const { t } = useTranslation();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await forgotPassword(email);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.forgotPassword.fallbackError'));
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="text-center">
        <h1 className="font-monument text-2xl text-chalk mb-4">{t('auth.forgotPassword.successTitle')}</h1>
        <p className="text-steel font-body text-sm mb-6">
          {t('auth.forgotPassword.successBefore')}{' '}
          <span className="text-chalk">{email}</span>
          {t('auth.forgotPassword.successAfter')}
        </p>
        <Link
          href="/login"
          className="inline-block py-2 px-6 bg-pit-orange text-asphalt font-monument text-lg rounded
            hover:brightness-110 transition-all"
        >
          {t('auth.forgotPassword.backToLogin')}
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-2 text-center">{t('auth.forgotPassword.title')}</h1>
      <p className="text-steel font-body text-sm text-center mb-6">
        {t('auth.forgotPassword.description')}
      </p>

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <FormField
          label={t('auth.forgotPassword.email')}
          type="email"
          placeholder={t('auth.forgotPassword.emailPlaceholder')}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />

        <button
          type="submit"
          disabled={loading}
          className="w-full mt-2 py-3 bg-pit-orange text-asphalt font-monument text-lg tracking-wider
            rounded hover:brightness-110 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? t('auth.forgotPassword.submitting') : t('auth.forgotPassword.submit')}
        </button>
      </form>

      <div className="mt-6 text-center">
        <Link href="/login" className="text-pit-orange hover:underline font-body text-sm">
          {t('auth.forgotPassword.backToLogin')}
        </Link>
      </div>
    </div>
  );
}
