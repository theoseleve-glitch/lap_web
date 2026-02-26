'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FormField } from '@/components/app/FormField';
import { register } from '@/lib/auth';

export default function RegisterPage() {
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await register(email, password, displayName);
      router.push('/login?registered=true');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1 className="font-monument text-2xl text-chalk mb-6 text-center">Create Account</h1>

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded">
          <p className="text-safety-red font-telemetry text-sm">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <FormField
          label="Display Name"
          type="text"
          placeholder="Your name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          required
        />
        <FormField
          label="Email"
          type="email"
          placeholder="driver@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
        />
        <FormField
          label="Password"
          type="password"
          placeholder="Minimum 8 characters"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
        />
        <FormField
          label="Confirm Password"
          type="password"
          placeholder="Re-enter password"
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
          {loading ? 'Creating account...' : 'Create Account'}
        </button>
      </form>

      <div className="mt-6 text-center">
        <p className="text-steel font-body text-sm">
          Already have an account?{' '}
          <Link href="/login" className="text-pit-orange hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
