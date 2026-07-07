'use client';

import { useState, useRef, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormField } from '@/components/app/FormField';
import { useAuth } from '@/hooks/useAuth';
import { OAuthButtons } from '@/components/auth/OAuthButtons';
import { TurnstileWidget } from '@/components/auth/TurnstileWidget';
import { useTranslation } from '@/i18n';
import { getSafeRedirect } from '@/lib/safe-redirect';

function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const searchParams = useSearchParams();
  const redirect = getSafeRedirect(searchParams.get('redirect'), '/app/dashboard');
  const oauthError = searchParams.get('error');
  const { login, verify2fa, loading, error } = useAuth();
  const { t } = useTranslation();

  // 2FA state
  const [twoFaStep, setTwoFaStep] = useState(false);
  const [tempToken, setTempToken] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [useBackupCode, setUseBackupCode] = useState(false);
  const codeInputRef = useRef<HTMLInputElement>(null);

  // Step-up challenge (Cloudflare Turnstile) state -- set when the backend
  // responds 428 challenge_required (see lib/auth.ts::ChallengeRequired).
  const [challengeSitekey, setChallengeSitekey] = useState<string | null>(null);

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = await login(email, password, redirect);
    if (result && 'requires_2fa' in result && result.requires_2fa) {
      setTempToken(result.temp_token);
      setTwoFaStep(true);
      // Focus the code input after render
      setTimeout(() => codeInputRef.current?.focus(), 100);
      return;
    }
    if (result && 'challenge_required' in result && result.challenge_required) {
      setChallengeSitekey(process.env.NEXT_PUBLIC_TURNSTILE_SITEKEY || result.sitekey);
    }
  };

  /** Called once the Turnstile widget produces a token -- resubmit the same
   * credentials with the token attached so the backend re-checks it. */
  const handleTurnstileToken = async (token: string) => {
    await login(email, password, redirect, token);
  };

  const handle2faSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await verify2fa(tempToken, totpCode, useBackupCode, redirect);
  };

  const handleBackToLogin = () => {
    setTwoFaStep(false);
    setTempToken('');
    setTotpCode('');
    setUseBackupCode(false);
  };

  const displayError = error ?? (oauthError ? `${t('auth.login.oauthError')} ${oauthError.replace(/_/g, ' ')}` : null);

  // --- 2FA verification step ---
  if (twoFaStep) {
    return (
      <div>
        <h1 className="font-monument text-2xl text-chalk mb-2 text-center">
          {t('auth.login.2fa.title')}
        </h1>
        <p className="text-steel font-body text-sm text-center mb-6">
          {useBackupCode
            ? t('auth.login.2fa.backupPrompt')
            : t('auth.login.2fa.totpPrompt')}
        </p>

        {displayError && (
          <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
            <p className="text-safety-red font-telemetry text-sm">{displayError}</p>
          </div>
        )}

        <form onSubmit={handle2faSubmit}>
          <FormField
            ref={codeInputRef}
            label={useBackupCode ? t('auth.login.2fa.backupLabel') : t('auth.login.2fa.totpLabel')}
            type="text"
            placeholder={useBackupCode ? t('auth.login.2fa.backupPlaceholder') : t('auth.login.2fa.totpPlaceholder')}
            value={totpCode}
            onChange={(e) => setTotpCode(e.target.value)}
            required
            autoComplete="one-time-code"
            inputMode={useBackupCode ? 'text' : 'numeric'}
            pattern={useBackupCode ? undefined : '[0-9]{6}'}
            maxLength={useBackupCode ? 20 : 6}
          />

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-2 py-3 bg-pit-orange text-white font-monument text-lg tracking-wider
              rounded hover:brightness-110 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? t('auth.login.2fa.verifying') : t('auth.login.2fa.verify')}
          </button>
        </form>

        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => {
              setUseBackupCode(!useBackupCode);
              setTotpCode('');
            }}
            className="text-pit-orange hover:underline font-body text-sm"
          >
            {useBackupCode ? t('auth.login.2fa.useApp') : t('auth.login.2fa.useBackup')}
          </button>
        </div>

        <div className="mt-2 text-center">
          <button
            type="button"
            onClick={handleBackToLogin}
            className="text-steel hover:text-chalk font-body text-sm transition-colors"
          >
            {t('auth.login.2fa.backToLogin')}
          </button>
        </div>
      </div>
    );
  }

  // --- Normal login form ---
  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-6 text-center">{t('auth.login.title')}</h1>

      {displayError && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{displayError}</p>
        </div>
      )}

      <form onSubmit={handleLoginSubmit}>
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

        <div className="flex justify-end mb-2">
          <Link
            href="/forgot-password"
            className="text-pit-orange hover:underline font-body text-sm"
          >
            {t('auth.login.forgotPassword')}
          </Link>
        </div>

        {challengeSitekey && (
          <TurnstileWidget sitekey={challengeSitekey} onToken={handleTurnstileToken} />
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full mt-2 py-3 bg-pit-orange text-white font-monument text-lg tracking-wider
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
