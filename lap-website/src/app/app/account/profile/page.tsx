'use client';

import { useState, useEffect, useCallback, useId } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { PageHeader } from '@/components/app';
import { apiFetch } from '@/lib/api-client';

/* ── Types ────────────────────────────────────────────────── */

interface NotificationPrefs {
  report_ready?: boolean;
  billing_alerts?: boolean;
  product_updates?: boolean;
  weekly_digest?: boolean;
}

interface Preferences {
  language?: string;
  timezone?: string;
  units?: string;
  notifications?: NotificationPrefs;
}

interface UserProfile {
  id: number;
  email: string;
  display_name: string;
  avatar_url: string | null;
  email_verified: boolean;
  plan_tier: string;
  subscription_status: string;
  preferences: Preferences;
}

/* ── Constants ────────────────────────────────────────────── */

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'de', label: 'Deutsch' },
  { value: 'es', label: 'Espa\u00f1ol' },
  { value: 'fr', label: 'Fran\u00e7ais' },
  { value: 'it', label: 'Italiano' },
  { value: 'pt', label: 'Portugu\u00eas' },
  { value: 'zh', label: '\u4E2D\u6587' },
] as const;

const TIMEZONES = [
  { value: 'UTC', label: 'UTC' },
  { value: 'Europe/London', label: 'London (GMT/BST)' },
  { value: 'Europe/Paris', label: 'Paris (CET/CEST)' },
  { value: 'Europe/Berlin', label: 'Berlin (CET/CEST)' },
  { value: 'Europe/Rome', label: 'Rome (CET/CEST)' },
  { value: 'Europe/Madrid', label: 'Madrid (CET/CEST)' },
  { value: 'America/New_York', label: 'New York (EST/EDT)' },
  { value: 'America/Chicago', label: 'Chicago (CST/CDT)' },
  { value: 'America/Denver', label: 'Denver (MST/MDT)' },
  { value: 'America/Los_Angeles', label: 'Los Angeles (PST/PDT)' },
  { value: 'America/Sao_Paulo', label: 'S\u00e3o Paulo (BRT)' },
  { value: 'Asia/Tokyo', label: 'Tokyo (JST)' },
  { value: 'Asia/Shanghai', label: 'Shanghai (CST)' },
  { value: 'Asia/Dubai', label: 'Dubai (GST)' },
  { value: 'Australia/Sydney', label: 'Sydney (AEST/AEDT)' },
] as const;

/* ── Toggle Switch Component ──────────────────────────────── */

function ToggleSwitch({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (val: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        checked ? 'bg-acid-green' : 'bg-steel/30'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full bg-chalk transition-transform ${
          checked ? 'translate-x-[18px]' : 'translate-x-[3px]'
        }`}
      />
    </button>
  );
}

/* ── Page ─────────────────────────────────────────────────── */

export default function ProfilePage() {
  const queryClient = useQueryClient();
  const fieldId = useId();

  const { data: profile, isLoading } = useQuery<UserProfile>({
    queryKey: ['account', 'profile'],
    queryFn: () => apiFetch<UserProfile>('/me'),
    staleTime: 60_000,
  });

  /* ── Local form state ─────────────────────────────── */
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [language, setLanguage] = useState('en');
  const [timezone, setTimezone] = useState('UTC');
  const [units, setUnits] = useState('metric');
  const [notifications, setNotifications] = useState<NotificationPrefs>({
    report_ready: true,
    billing_alerts: true,
    product_updates: false,
    weekly_digest: false,
  });

  // Sync server data into local state once loaded
  useEffect(() => {
    if (!profile) return;
    setDisplayName(profile.display_name || '');
    setEmail(profile.email || '');
    setAvatarUrl(profile.avatar_url || '');
    setLanguage(profile.preferences?.language || 'en');
    setTimezone(profile.preferences?.timezone || 'UTC');
    setUnits(profile.preferences?.units || 'metric');
    setNotifications({
      report_ready: profile.preferences?.notifications?.report_ready ?? true,
      billing_alerts: profile.preferences?.notifications?.billing_alerts ?? true,
      product_updates: profile.preferences?.notifications?.product_updates ?? false,
      weekly_digest: profile.preferences?.notifications?.weekly_digest ?? false,
    });
  }, [profile]);

  /* ── Profile save mutation ────────────────────────── */
  const profileMutation = useMutation({
    mutationFn: (data: { display_name?: string; email?: string; avatar_url?: string }) =>
      apiFetch<UserProfile>('/account/profile', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['account', 'profile'] });
    },
  });

  /* ── Preferences save mutation ────────────────────── */
  const prefsMutation = useMutation({
    mutationFn: (prefs: Preferences) =>
      apiFetch<UserProfile>('/account/profile', {
        method: 'PATCH',
        body: JSON.stringify({ preferences: prefs }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['account', 'profile'] });
    },
  });

  /* ── Auto-save notification toggles ───────────────── */
  const handleNotificationToggle = useCallback(
    (key: keyof NotificationPrefs, value: boolean) => {
      const updated = { ...notifications, [key]: value };
      setNotifications(updated);
      prefsMutation.mutate({
        language,
        timezone,
        units,
        notifications: updated,
      });
    },
    [notifications, language, timezone, units, prefsMutation],
  );

  return (
    <div>
      <PageHeader title="Profile" subtitle="Manage your personal information and preferences" />

      {/* ── Personal Info ──────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Personal Information</h2>
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-10 bg-steel/10 rounded" />
            <div className="h-10 bg-steel/10 rounded" />
            <div className="h-10 bg-steel/10 rounded" />
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              profileMutation.mutate({
                display_name: displayName,
                email,
                avatar_url: avatarUrl || undefined,
              });
            }}
            className="space-y-4"
          >
            {/* Display name */}
            <div>
              <label htmlFor={`${fieldId}-name`} className="block text-steel text-xs font-telemetry mb-1">Display Name</label>
              <input
                id={`${fieldId}-name`}
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Your name"
                disabled={profileMutation.isPending}
                className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
              />
            </div>

            {/* Email */}
            <div>
              <label htmlFor={`${fieldId}-email`} className="block text-steel text-xs font-telemetry mb-1">Email</label>
              <div className="flex items-center gap-2">
                <input
                  id={`${fieldId}-email`}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  disabled={profileMutation.isPending}
                  className="flex-1 bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
                />
                {profile?.email_verified && (
                  <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-telemetry bg-acid-green/20 text-acid-green">
                    Verified
                  </span>
                )}
                {profile && !profile.email_verified && (
                  <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-telemetry bg-marshal-yellow/20 text-marshal-yellow">
                    Unverified
                  </span>
                )}
              </div>
            </div>

            {/* Avatar URL */}
            <div>
              <label htmlFor={`${fieldId}-avatar`} className="block text-steel text-xs font-telemetry mb-1">Avatar URL</label>
              <input
                id={`${fieldId}-avatar`}
                type="url"
                value={avatarUrl}
                onChange={(e) => setAvatarUrl(e.target.value)}
                placeholder="https://example.com/avatar.jpg"
                disabled={profileMutation.isPending}
                className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
              />
              <p className="text-steel text-[10px] font-body mt-1">
                Paste a URL to an image. No file upload supported.
              </p>
            </div>

            {profileMutation.isError && (
              <p className="text-safety-red text-xs font-telemetry">
                {(profileMutation.error as Error).message}
              </p>
            )}
            {profileMutation.isSuccess && (
              <p className="text-acid-green text-xs font-telemetry">Profile updated</p>
            )}

            <button
              type="submit"
              disabled={profileMutation.isPending}
              className="bg-gold text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
            >
              {profileMutation.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </form>
        )}
      </div>

      {/* ── Preferences ───────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Preferences</h2>
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-10 bg-steel/10 rounded" />
            <div className="h-10 bg-steel/10 rounded" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* Language */}
            <div>
              <label htmlFor={`${fieldId}-lang`} className="block text-steel text-xs font-telemetry mb-1">Language</label>
              <select
                id={`${fieldId}-lang`}
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                disabled={prefsMutation.isPending}
                className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {LANGUAGES.map((lang) => (
                  <option key={lang.value} value={lang.value}>
                    {lang.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Timezone */}
            <div>
              <label htmlFor={`${fieldId}-tz`} className="block text-steel text-xs font-telemetry mb-1">Timezone</label>
              <select
                id={`${fieldId}-tz`}
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                disabled={prefsMutation.isPending}
                className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz.value} value={tz.value}>
                    {tz.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Units */}
            <div>
              <label className="block text-steel text-xs font-telemetry mb-1">Units</label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="units"
                    value="metric"
                    checked={units === 'metric'}
                    onChange={() => setUnits('metric')}
                    disabled={prefsMutation.isPending}
                    className="w-4 h-4 accent-acid-green disabled:opacity-60"
                  />
                  <span className="text-chalk text-sm font-body">Metric (km/h, kg)</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="units"
                    value="imperial"
                    checked={units === 'imperial'}
                    onChange={() => setUnits('imperial')}
                    disabled={prefsMutation.isPending}
                    className="w-4 h-4 accent-acid-green disabled:opacity-60"
                  />
                  <span className="text-chalk text-sm font-body">Imperial (mph, lbs)</span>
                </label>
              </div>
            </div>

            {prefsMutation.isError && (
              <p className="text-safety-red text-xs font-telemetry">
                {(prefsMutation.error as Error).message}
              </p>
            )}

            <button
              type="button"
              onClick={() =>
                prefsMutation.mutate({
                  language,
                  timezone,
                  units,
                  notifications,
                })
              }
              disabled={prefsMutation.isPending}
              className="bg-gold text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
            >
              {prefsMutation.isPending ? 'Saving...' : 'Save Preferences'}
            </button>
            {prefsMutation.isSuccess && (
              <p className="text-acid-green text-xs font-telemetry mt-2">Preferences saved</p>
            )}
          </div>
        )}
      </div>

      {/* ── Notifications ─────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Notifications</h2>
        {isLoading ? (
          <div className="animate-pulse space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-8 bg-steel/10 rounded" />
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-chalk text-sm font-body">Report Ready</p>
                <p className="text-steel text-xs font-body">Notified when your analysis report is complete</p>
              </div>
              <ToggleSwitch
                checked={notifications.report_ready ?? true}
                onChange={(val) => handleNotificationToggle('report_ready', val)}
                disabled={prefsMutation.isPending}
              />
            </div>

            <div className="border-t border-steel/10" />

            <div className="flex items-center justify-between">
              <div>
                <p className="text-chalk text-sm font-body">Billing Alerts</p>
                <p className="text-steel text-xs font-body">Payment confirmations and subscription changes</p>
              </div>
              <ToggleSwitch
                checked={notifications.billing_alerts ?? true}
                onChange={(val) => handleNotificationToggle('billing_alerts', val)}
                disabled={prefsMutation.isPending}
              />
            </div>

            <div className="border-t border-steel/10" />

            <div className="flex items-center justify-between">
              <div>
                <p className="text-chalk text-sm font-body">Product Updates</p>
                <p className="text-steel text-xs font-body">New features, improvements, and announcements</p>
              </div>
              <ToggleSwitch
                checked={notifications.product_updates ?? false}
                onChange={(val) => handleNotificationToggle('product_updates', val)}
                disabled={prefsMutation.isPending}
              />
            </div>

            <div className="border-t border-steel/10" />

            <div className="flex items-center justify-between">
              <div>
                <p className="text-chalk text-sm font-body">Weekly Digest</p>
                <p className="text-steel text-xs font-body">Weekly summary of your performance and sessions</p>
              </div>
              <ToggleSwitch
                checked={notifications.weekly_digest ?? false}
                onChange={(val) => handleNotificationToggle('weekly_digest', val)}
                disabled={prefsMutation.isPending}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
