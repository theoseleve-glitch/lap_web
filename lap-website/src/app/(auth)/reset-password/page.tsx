'use client';

import { useState, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormField } from '@/components/app/FormField';
import { resetPassword } from '@/lib/auth';

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token');

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  if (!token) {
    return (
      <div className="text-center">
        <h1 className="font-monument text-2xl text-chalk mb-4">Invalid Link</h1>
        <p className="text-safety-red font-body text-sm mb-6">
          This password reset link is invalid or missing a token.
        </p>
        <Link
          href="/forgot-password"
          className="text-pit-orange hover:underline font-body text-sm"
        >
          Request a new reset link
        </Link>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setLoading(true);
    try {
      await resetPassword(token, password);
      setSuccess(true);
    } catch (err) {
      if (err instanceof Error) {
        // Provide a user-friendly message for expired tokens
        if (err.message.toLowerCase().includes('expired') || err.message.toLowerCase().includes('invalid')) {
          setError('This reset link has expired or is invalid. Please request a new one.');
        } else {
          setError(err.message);
        }
      } else {
        setError('Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="text-center">
        <h1 className="font-monument text-2xl text-chalk mb-4">Password Reset</h1>
        <p className="text-acid-green font-body text-sm mb-6">
          Your password has been reset successfully.
        </p>
        <Link
          href="/login"
          className="inline-block py-2 px-6 bg-pit-orange text-asphalt font-monument text-lg rounded
            hover:brightness-110 transition-all"
        >
          Sign In
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-2 text-center">Reset Password</h1>
      <p className="text-steel font-body text-sm text-center mb-6">
        Enter your new password below.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <FormField
          label="New Password"
          type="password"
          placeholder="At least 8 characters"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
          minLength={8}
        />
        <FormField
          label="Confirm Password"
          type="password"
          placeholder="Re-enter your password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          required
          autoComplete="new-password"
        />

        <button
          type="submit"
          disabled={loading}
          className="w-full mt-2 py-3 bg-pit-orange text-asphalt font-monument text-lg tracking-wider
            rounded hover:brightness-110 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Resetting...' : 'Reset Password'}
        </button>
      </form>

      <div className="mt-6 text-center">
        <Link href="/login" className="text-pit-orange hover:underline font-body text-sm">
          Back to login
        </Link>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="text-center">
          <h1 className="font-monument text-2xl text-chalk mb-4">Reset Password</h1>
          <p className="text-steel font-body">Loading...</p>
        </div>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}
