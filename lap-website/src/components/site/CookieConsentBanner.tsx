'use client';

import { useEffect, useState } from 'react';

type ConsentState = 'unknown' | 'granted' | 'denied';

function readConsent(): ConsentState {
  if (typeof document === 'undefined') return 'unknown';
  const raw = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('lap_cookie_consent='));
  if (!raw) return 'unknown';
  const value = raw.split('=').slice(1).join('=');
  if (value === 'granted' || value === 'denied') return value;
  return 'unknown';
}

function setConsent(value: Exclude<ConsentState, 'unknown'>) {
  document.cookie = `lap_cookie_consent=${value}; path=/; max-age=${60 * 60 * 24 * 365}; samesite=lax`;
}

export function CookieConsentBanner() {
  const [consent, setConsentState] = useState<ConsentState>('unknown');

  useEffect(() => {
    setConsentState(readConsent());
  }, []);

  if (consent !== 'unknown') return null;

  return (
    <aside className="fixed left-4 right-4 bottom-4 z-[180] border border-steel/30 bg-asphalt/95 backdrop-blur p-4 md:left-8 md:right-8">
      <p className="text-sm text-steel mb-3">
        Allow analytics and experiment cookies so we can improve the buying journey.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          className="border border-pit-orange bg-pit-orange text-asphalt px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase"
          onClick={() => {
            setConsent('granted');
            setConsentState('granted');
            window.location.reload();
          }}
        >
          Accept
        </button>
        <button
          className="border border-steel/40 px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel"
          onClick={() => {
            setConsent('denied');
            setConsentState('denied');
            window.location.reload();
          }}
        >
          Decline
        </button>
      </div>
    </aside>
  );
}
