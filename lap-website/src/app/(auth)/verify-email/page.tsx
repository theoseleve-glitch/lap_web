'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { verifyEmail } from '@/lib/auth';

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token');
  const [status, setStatus] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setError('No verification token provided');
      return;
    }

    verifyEmail(token)
      .then(() => setStatus('success'))
      .catch((err) => {
        setStatus('error');
        setError(err instanceof Error ? err.message : 'Verification failed');
      });
  }, [token]);

  return (
    <>
      {status === 'verifying' && (
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
          <p className="text-steel font-body">Verifying your email...</p>
        </div>
      )}

      {status === 'success' && (
        <div>
          <p className="text-acid-green font-body mb-4">Your email has been verified!</p>
          <Link
            href="/login"
            className="inline-block py-2 px-6 bg-pit-orange text-asphalt font-monument text-lg rounded hover:brightness-110 transition-all"
          >
            Sign In
          </Link>
        </div>
      )}

      {status === 'error' && (
        <div>
          <p className="text-safety-red font-body mb-4">{error || 'Verification failed'}</p>
          <Link href="/login" className="text-pit-orange hover:underline font-body">
            Back to login
          </Link>
        </div>
      )}
    </>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="text-center">
      <h1 className="font-monument text-2xl text-chalk mb-6">Email Verification</h1>
      <Suspense
        fallback={
          <div className="flex flex-col items-center gap-4">
            <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
            <p className="text-steel font-body">Loading...</p>
          </div>
        }
      >
        <VerifyEmailContent />
      </Suspense>
    </div>
  );
}
