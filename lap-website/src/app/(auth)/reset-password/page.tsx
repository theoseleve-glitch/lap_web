'use client';

import { useState, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormField } from '@/components/app/FormField';
import { resetPassword } from '@/lib/auth';
import { useTranslation } from '@/i18n';

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token');
  const { t } = useTranslation();

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  if (!token) {
    return (
      <div className="text-center">
        <h1 className="font-monument text-2xl text-chalk mb-4">{t('auth.resetPassword.invalidTitle')}</h1>
        <p className="text-safety-red font-body text-sm mb-6">
          {t('auth.resetPassword.invalidMessage')}
        </p>
        <Link
          href="/forgot-password"
          className="text-pit-orange hover:underline font-body text-sm"
        >
          {t('auth.resetPassword.requestNew')}
        </Link>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError(t('auth.resetPassword.mismatch'));
      return;
    }
    if (password.length < 8) {
      setError(t('auth.resetPassword.tooShort'));
      return;
    }

    setLoading(true);
    try {
      await resetPassword(token, password);
      setSuccess(true);
    } catch (err) {
      if (err instanceof Error) {
        if (err.message.toLowerCase().includes('expired') || err.message.toLowerCase().includes('invalid')) {
          setError(t('auth.resetPassword.expiredLink'));
        } else {
          setError(err.message);
        }
      } else {
        setError(t('auth.resetPassword.fallbackError'));
      }
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="text-center">
        <h1 className="font-monument text-2xl text-chalk mb-4">{t('auth.resetPassword.successTitle')}</h1>
        <p className="text-acid-green font-body text-sm mb-6">
          {t('auth.resetPassword.successMessage')}
        </p>
        <Link
          href="/login"
          className="inline-block py-2 px-6 bg-pit-orange text-white font-monument text-lg rounded
            hover:brightness-110 transition-all"
        >
          {t('auth.resetPassword.signIn')}
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-2 text-center">{t('auth.resetPassword.title')}</h1>
      <p className="text-steel font-body text-sm text-center mb-6">
        {t('auth.resetPassword.description')}
      </p>

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <FormField
          label={t('auth.resetPassword.newPassword')}
          type="password"
          placeholder={t('auth.resetPassword.newPasswordPlaceholder')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
          minLength={8}
        />
        <FormField
          label={t('auth.resetPassword.confirmPassword')}
          type="password"
          placeholder={t('auth.resetPassword.confirmPlaceholder')}
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
          autoComplete="new-password"
        />

        <button
          type="submit"
          disabled={loading}
          className="w-full mt-2 py-3 bg-pit-orange text-white font-monument text-lg tracking-wider
            rounded hover:brightness-110 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? t('auth.resetPassword.submitting') : t('auth.resetPassword.submit')}
        </button>
      </form>

      <div className="mt-6 text-center">
        <Link href="/login" className="text-pit-orange hover:underline font-body text-sm">
          {t('auth.resetPassword.backToLogin')}
        </Link>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  const { t } = useTranslation();

  return (
    <Suspense
      fallback={
        <div className="text-center">
          <h1 className="font-monument text-2xl text-chalk mb-4">{t('auth.resetPassword.title')}</h1>
          <p className="text-steel font-body">{t('auth.resetPassword.loading')}</p>
        </div>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}
