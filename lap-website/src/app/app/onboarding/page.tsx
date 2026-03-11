'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { PageIntro } from '@/components/ui/PageIntro';
import { api } from '@/lib/api-client';
import { getUserProfile, setUserProfile } from '@/lib/auth-store';

export default function OnboardingPage() {
  const router = useRouter();
  const profile = getUserProfile();

  const [displayName, setDisplayName] = useState(profile?.display_name || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const name = displayName.trim();
    if (!name) {
      setError('Please enter your name.');
      return;
    }

    setSaving(true);
    setError('');

    try {
      await api.patch('/account/profile', { display_name: name });

      // Update cached profile so AuthGuard passes on next check
      const current = getUserProfile();
      setUserProfile(
        current
          ? { ...current, display_name: name }
          : { id: 0, email: '', display_name: name },
      );

      router.replace('/app/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setSaving(false);
    }
  }, [displayName, router]);

  return (
    <div>
      <PageIntro
        title="Complete Your Profile"
        subtitle="Tell us who's behind the wheel before you start analyzing telemetry."
      />

      <form onSubmit={handleSubmit} className="max-w-md">
        <div className="mb-6">
          <label
            htmlFor="display-name"
            className="block text-sm font-telemetry text-steel mb-1.5 uppercase tracking-wider"
          >
            Your Name <span className="text-safety-red">*</span>
          </label>
          <input
            id="display-name"
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            autoFocus
            placeholder="e.g. Alex Rossi"
            className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
              placeholder:text-steel/60 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
          />
          <p className="mt-1.5 text-xs font-body text-steel">
            This will be used as the default driver name on your uploads.
          </p>
        </div>

        {error && (
          <div
            className="mb-4 p-3 rounded-lg bg-safety-red/10 border border-safety-red/20 text-safety-red text-sm font-body"
            role="alert"
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={saving || !displayName.trim()}
          className="px-6 py-3 bg-gold text-carbon font-monument text-sm rounded-lg
            hover:bg-gold/90 transition-colors
            disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-gold"
        >
          {saving ? 'Saving...' : 'Start Analyzing'}
        </button>
      </form>
    </div>
  );
}
