'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

/* ── Types ────────────────────────────────────────────────── */

interface CookiePreferences {
  necessary: true;
  analytics: boolean;
  marketing: boolean;
  timestamp: string;
}

const STORAGE_KEY = 'lap_cookie_consent';
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const CURRENT_VERSION = '1';

/* ── Helpers ──────────────────────────────────────────────── */

function getStoredPreferences(): CookiePreferences | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function savePreferences(prefs: CookiePreferences) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));

  // Dispatch event so other components can react
  window.dispatchEvent(new CustomEvent('cookie-consent-update', { detail: prefs }));
}

/* ── Component ────────────────────────────────────────────── */

export function CookieConsent() {
  const [visible, setVisible] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [analytics, setAnalytics] = useState(false);
  const [marketing, setMarketing] = useState(false);

  useEffect(() => {
    const stored = getStoredPreferences();
    if (!stored) {
      setVisible(true);
    }
  }, []);

  if (!visible) return null;

  const handleAcceptAll = () => {
    const prefs: CookiePreferences = {
      necessary: true,
      analytics: true,
      marketing: true,
      timestamp: new Date().toISOString(),
    };
    savePreferences(prefs);
    setVisible(false);
  };

  const handleRejectOptional = () => {
    const prefs: CookiePreferences = {
      necessary: true,
      analytics: false,
      marketing: false,
      timestamp: new Date().toISOString(),
    };
    savePreferences(prefs);
    setVisible(false);
  };

  const handleSaveCustom = () => {
    const prefs: CookiePreferences = {
      necessary: true,
      analytics,
      marketing,
      timestamp: new Date().toISOString(),
    };
    savePreferences(prefs);
    setVisible(false);
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 p-4 md:p-6">
      <div className="max-w-2xl mx-auto bg-concrete border border-steel/30 rounded-lg shadow-2xl p-5">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <h3 className="font-monument text-sm text-chalk">Cookie Preferences</h3>
            <p className="text-steel text-xs font-body mt-1">
              We use cookies to improve your experience. Necessary cookies are always active.
              See our{' '}
              <Link href="/privacy" className="text-acid-green hover:underline">
                Privacy Policy
              </Link>
              .
            </p>
          </div>
        </div>

        {expanded ? (
          <div className="space-y-3 mb-4">
            {/* Necessary */}
            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                checked
                disabled
                className="w-4 h-4 rounded accent-acid-green"
              />
              <div>
                <span className="text-chalk text-xs font-telemetry">Necessary</span>
                <p className="text-steel text-[10px] font-body">
                  Required for the site to function (auth, security, preferences).
                </p>
              </div>
            </label>

            {/* Analytics */}
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={analytics}
                onChange={(e) => setAnalytics(e.target.checked)}
                className="w-4 h-4 rounded accent-acid-green"
              />
              <div>
                <span className="text-chalk text-xs font-telemetry">Analytics</span>
                <p className="text-steel text-[10px] font-body">
                  Help us understand how the site is used to improve the experience.
                </p>
              </div>
            </label>

            {/* Marketing */}
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={marketing}
                onChange={(e) => setMarketing(e.target.checked)}
                className="w-4 h-4 rounded accent-acid-green"
              />
              <div>
                <span className="text-chalk text-xs font-telemetry">Marketing</span>
                <p className="text-steel text-[10px] font-body">
                  Allow personalized content and promotions based on your interests.
                </p>
              </div>
            </label>

            <button
              type="button"
              onClick={handleSaveCustom}
              className="w-full bg-gold text-asphalt font-telemetry text-sm py-2 rounded-md hover:brightness-110 transition"
            >
              Save Preferences
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleAcceptAll}
              className="bg-gold text-asphalt font-telemetry text-xs px-4 py-2 rounded-md hover:brightness-110 transition"
            >
              Accept All
            </button>
            <button
              type="button"
              onClick={handleRejectOptional}
              className="bg-concrete border border-steel/30 text-steel font-telemetry text-xs px-4 py-2 rounded-md hover:text-chalk transition"
            >
              Necessary Only
            </button>
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="bg-concrete border border-steel/30 text-steel font-telemetry text-xs px-4 py-2 rounded-md hover:text-chalk transition"
            >
              Manage Cookies
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Helper hook for other components ─────────────────────── */

export function getCookieConsent(): CookiePreferences | null {
  return getStoredPreferences();
}

export function hasAnalyticsConsent(): boolean {
  const prefs = getStoredPreferences();
  return prefs?.analytics ?? false;
}

export function hasMarketingConsent(): boolean {
  const prefs = getStoredPreferences();
  return prefs?.marketing ?? false;
}
