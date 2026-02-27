'use client';

import { useState } from 'react';
import Link from 'next/link';
import { FormField } from '@/components/app/FormField';
import { forgotPassword } from '@/lib/auth';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await forgotPassword(email);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    return (
      <div className="text-center">
        <h1 className="font-monument text-2xl text-chalk mb-4">Check Your Email</h1>
        <p className="text-steel font-body text-sm mb-6">
          If an account exists for <span className="text-chalk">{email}</span>, we sent a password
          reset link. Check your inbox and spam folder.
        </p>
        <Link
          href="/login"
          className="inline-block py-2 px-6 bg-pit-orange text-asphalt font-monument text-lg rounded
            hover:brightness-110 transition-all"
        >
          Back to Login
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-2 text-center">Forgot Password</h1>
      <p className="text-steel font-body text-sm text-center mb-6">
        Enter your email address and we will send you a link to reset your password.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <FormField
          label="Email"
          type="email"
          placeholder="you@example.com"
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
          {loading ? 'Sending...' : 'Send Reset Link'}
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
