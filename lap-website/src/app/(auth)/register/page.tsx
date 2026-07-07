'use client';

import { useState, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormField } from '@/components/app/FormField';
import { useAuth } from '@/hooks/useAuth';
import { OAuthButtons } from '@/components/auth/OAuthButtons';
import { useTranslation } from '@/i18n';
import { getSafeRedirect } from '@/lib/safe-redirect';

function getPasswordStrength(pw: string): { score: 0 | 1 | 2 | 3 | 4; label: string; color: string } {
  if (!pw) return { score: 0, label: '', color: '' };
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  if (s <= 1) return { score: 1, label: 'Weak', color: 'bg-safety-red' };
  if (s === 2) return { score: 2, label: 'Fair', color: 'bg-marshal-yellow' };
  if (s === 3) return { score: 3, label: 'Good', color: 'bg-acid-green/60' };
  return { score: 4, label: 'Strong', color: 'bg-acid-green' };
}

function RegisterForm() {
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const searchParams = useSearchParams();
  const redirect = getSafeRedirect(searchParams.get('redirect'), '/app/dashboard');
  const { register, loading, error } = useAuth();
  const { t } = useTranslation();
  const strength = getPasswordStrength(password);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    if (password.length < 8) {
      setValidationError(t('auth.register.passwordTooShort'));
      return;
    }

    if (!agreedToTerms) {
      setValidationError('You must agree to the Terms of Service and Privacy Policy.');
      return;
    }

    await register(email, password, displayName || undefined, redirect);
  };

  const displayError = validationError ?? error;

  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-6 text-center">{t('auth.register.title')}</h1>

      <OAuthButtons />

      <div className="flex items-center gap-3 my-5">
        <div className="flex-1 h-px bg-steel/20" />
        <span className="text-steel font-telemetry text-[10px] tracking-wider uppercase">or sign up with email</span>
        <div className="flex-1 h-px bg-steel/20" />
      </div>

      {displayError && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{displayError}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <FormField
          label={t('auth.register.email')}
          type="email"
          placeholder={t('auth.register.emailPlaceholder')}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onBlur={() => setTouched((p) => ({ ...p, email: true }))}
          required
          autoComplete="email"
          valid={touched.email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)}
          error={touched.email && email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? 'Enter a valid email address' : undefined}
        />
        <FormField
          label={t('auth.register.password')}
          type="password"
          placeholder={t('auth.register.passwordPlaceholder')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onBlur={() => setTouched((p) => ({ ...p, password: true }))}
          required
          autoComplete="new-password"
          valid={touched.password && password.length >= 8}
          error={touched.password && password && password.length < 8 ? 'Password must be at least 8 characters' : undefined}
        />
        {password && (
          <div className="mb-4 -mt-2">
            <div className="flex gap-1 mb-1">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className={`h-1 flex-1 rounded-full transition-colors ${
                    i <= strength.score ? strength.color : 'bg-steel/20'
                  }`}
                />
              ))}
            </div>
            <p className="font-telemetry text-[10px] tracking-wider uppercase text-steel">
              {strength.label}
            </p>
          </div>
        )}
        <FormField
          label={t('auth.register.displayName')}
          type="text"
          placeholder={t('auth.register.displayNamePlaceholder')}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
        <p className="text-steel/50 font-telemetry text-[10px] -mt-2 mb-4">Optional — you can set this later in your profile</p>

        <label className="flex items-start gap-2 mb-4 cursor-pointer">
          <input
            type="checkbox"
            checked={agreedToTerms}
            onChange={(e) => setAgreedToTerms(e.target.checked)}
            className="mt-0.5 w-4 h-4 rounded accent-acid-green shrink-0"
            required
          />
          <span className="text-steel font-body text-xs leading-relaxed">
            I agree to the{' '}
            <Link href="/terms" className="text-pit-orange hover:underline">
              Terms of Service
            </Link>{' '}
            and{' '}
            <Link href="/privacy" className="text-pit-orange hover:underline">
              Privacy Policy
            </Link>
          </span>
        </label>

        <button
          type="submit"
          disabled={loading}
          className="w-full mt-2 py-3 bg-pit-orange text-white font-monument text-lg tracking-wider
            rounded hover:brightness-110 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? t('auth.register.submitting') : t('auth.register.submit')}
        </button>
      </form>

      <div className="mt-6 text-center">
        <p className="text-steel font-body text-sm">
          {t('auth.register.hasAccount')}{' '}
          <Link href="/login" className="text-pit-orange hover:underline">
            {t('auth.register.signIn')}
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  );
}
