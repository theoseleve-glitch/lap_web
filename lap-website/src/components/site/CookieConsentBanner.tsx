'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getConsent, setConsent, type ConsentState } from '@/lib/consent';

type Phase = 'hidden' | 'banner' | 'details';

const COOKIE_TABLE = [
  { name: 'lap_consent', provider: 'LAP', purpose: 'Stores your cookie preferences', expiry: '1 year', type: 'Necessary' },
  { name: 'lap_session_id', provider: 'LAP', purpose: 'Anonymous session identifier for UX', expiry: 'Session', type: 'Necessary' },
  { name: 'lap_attribution', provider: 'LAP', purpose: 'UTM attribution for marketing source tracking', expiry: '30 days', type: 'Marketing' },
  { name: 'lap_exp_*', provider: 'LAP', purpose: 'A/B experiment assignment', expiry: '30 days', type: 'Analytics' },
  { name: 'plausible (script)', provider: 'Plausible Analytics', purpose: 'Privacy-friendly page view and event analytics', expiry: 'No cookies (cookieless)', type: 'Analytics' },
] as const;

export function CookieConsentBanner() {
  const [phase, setPhase] = useState<Phase>('hidden');
  const [analytics, setAnalytics] = useState(false);
  const [marketing, setMarketing] = useState(false);

  useEffect(() => {
    const existing = getConsent();
    if (!existing) {
      setPhase('banner');
    }
  }, []);

  if (phase === 'hidden') return null;

  const accept = (state: ConsentState) => {
    setConsent(state);
    setPhase('hidden');
  };

  return (
    <aside
      role="dialog"
      aria-label="Cookie consent"
      className="fixed bottom-0 left-0 right-0 z-[180] border-t border-steel/30 bg-asphalt/95 backdrop-blur"
    >
      <div className="mx-auto max-w-3xl px-4 py-5 md:px-8">
        {phase === 'banner' && (
          <>
            <p className="text-sm text-steel mb-1">
              We use cookies to run the site and, with your permission, to measure usage via{' '}
              <span className="text-chalk">Plausible Analytics</span> (cookieless, EU-hosted).
            </p>
            <p className="text-xs text-steel/70 mb-3">
              See our{' '}
              <Link href="/privacy" className="text-pit-orange hover:underline">Privacy Policy</Link>
              {' '}and{' '}
              <Link href="/terms" className="text-pit-orange hover:underline">Terms</Link>.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => accept({ analytics: true, marketing: true })}
                className="border border-pit-orange bg-pit-orange text-asphalt px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase hover:brightness-110 transition"
              >
                Accept All
              </button>
              <button
                onClick={() => accept({ analytics: false, marketing: false })}
                className="border border-steel/40 px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition"
              >
                Necessary Only
              </button>
              <button
                onClick={() => setPhase('details')}
                className="border border-steel/40 px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition"
              >
                Manage Cookies
              </button>
            </div>
          </>
        )}

        {phase === 'details' && (
          <>
            <h3 className="font-telemetry text-xs tracking-[0.12em] uppercase text-chalk mb-3">
              Cookie Preferences
            </h3>

            {/* Category toggles */}
            <div className="space-y-2 mb-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" checked disabled className="w-4 h-4 accent-pit-orange" />
                <div>
                  <span className="text-chalk text-xs font-telemetry">Necessary</span>
                  <span className="text-steel text-[10px] ml-2">Always active</span>
                </div>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={analytics}
                  onChange={(e) => setAnalytics(e.target.checked)}
                  className="w-4 h-4 accent-pit-orange"
                />
                <div>
                  <span className="text-chalk text-xs font-telemetry">Analytics</span>
                  <span className="text-steel text-[10px] ml-2">Page views and usage patterns</span>
                </div>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={marketing}
                  onChange={(e) => setMarketing(e.target.checked)}
                  className="w-4 h-4 accent-pit-orange"
                />
                <div>
                  <span className="text-chalk text-xs font-telemetry">Marketing</span>
                  <span className="text-steel text-[10px] ml-2">Attribution and campaign tracking</span>
                </div>
              </label>
            </div>

            {/* Cookie lifetime table */}
            <details className="mb-4 group">
              <summary className="text-[10px] text-steel font-telemetry tracking-[0.12em] uppercase cursor-pointer hover:text-chalk">
                Cookie Details &amp; Lifetimes
              </summary>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-[11px] text-steel border-collapse">
                  <thead>
                    <tr className="border-b border-steel/20">
                      <th className="text-left py-1 pr-3 font-telemetry text-chalk">Name</th>
                      <th className="text-left py-1 pr-3 font-telemetry text-chalk">Provider</th>
                      <th className="text-left py-1 pr-3 font-telemetry text-chalk">Purpose</th>
                      <th className="text-left py-1 pr-3 font-telemetry text-chalk">Expiry</th>
                      <th className="text-left py-1 font-telemetry text-chalk">Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {COOKIE_TABLE.map((row) => (
                      <tr key={row.name} className="border-b border-steel/10">
                        <td className="py-1 pr-3 font-mono">{row.name}</td>
                        <td className="py-1 pr-3">{row.provider}</td>
                        <td className="py-1 pr-3">{row.purpose}</td>
                        <td className="py-1 pr-3">{row.expiry}</td>
                        <td className="py-1">{row.type}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => accept({ analytics, marketing })}
                className="border border-pit-orange bg-pit-orange text-asphalt px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase hover:brightness-110 transition"
              >
                Save Preferences
              </button>
              <button
                onClick={() => accept({ analytics: true, marketing: true })}
                className="border border-steel/40 px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition"
              >
                Accept All
              </button>
              <button
                onClick={() => setPhase('banner')}
                className="px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel hover:text-chalk transition"
              >
                Back
              </button>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
