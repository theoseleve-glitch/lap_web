'use client';

import { useEffect, useCallback, useRef } from 'react';
import { useRouter, usePathname } from 'next/navigation';

interface SessionExpiredModalProps {
  onRetry: () => void;
  retrying: boolean;
}

/**
 * Modal shown when the user's session expires mid-usage.
 * Offers a single "Retry" attempt (in case it was a transient network error)
 * then a "Log in" CTA that redirects to /login with returnTo.
 */
export function SessionExpiredModal({ onRetry, retrying }: SessionExpiredModalProps) {
  const router = useRouter();
  const pathname = usePathname();
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const handleLogin = useCallback(() => {
    const returnTo = encodeURIComponent(pathname);
    router.push(`/login?redirect=${returnTo}`);
  }, [pathname, router]);

  return (
    <dialog
      ref={dialogRef}
      className="fixed inset-0 z-50 bg-transparent backdrop:bg-carbon/70"
      aria-labelledby="session-expired-title"
      onClose={handleLogin}
    >
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="w-full max-w-sm rounded-lg bg-concrete border border-steel/20 p-6 shadow-xl">
          <div className="flex items-center gap-3 mb-4">
            <div className="flex items-center justify-center w-10 h-10 rounded-full bg-pit-orange/10" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="text-pit-orange">
                <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
                <path d="M10 6v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <circle cx="10" cy="14" r="0.75" fill="currentColor" />
              </svg>
            </div>
            <h2 id="session-expired-title" className="font-monument text-lg text-chalk">
              Session expired
            </h2>
          </div>

          <p className="text-steel font-body text-sm mb-6">
            Your session has expired. You can try to reconnect or log in again.
          </p>

          <div className="flex items-center gap-3">
            <button
              onClick={onRetry}
              disabled={retrying}
              className="px-4 py-2.5 border border-steel/30 text-chalk font-telemetry text-sm rounded
                hover:bg-asphalt/50 transition-colors
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {retrying ? (
                <span className="flex items-center gap-2">
                  <span className="w-3 h-3 border-2 border-steel/30 border-t-chalk rounded-full animate-spin" />
                  Retrying...
                </span>
              ) : (
                'Retry'
              )}
            </button>
            <button
              onClick={handleLogin}
              className="px-4 py-2.5 bg-gold text-carbon font-monument text-sm rounded
                hover:bg-gold/90 transition-colors"
            >
              Log in
            </button>
          </div>
        </div>
      </div>
    </dialog>
  );
}
