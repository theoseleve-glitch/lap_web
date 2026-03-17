'use client';

import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { PageIntro } from '@/components/ui/PageIntro';
import { apiFetch } from '@/lib/api-client';

/* ── Types ────────────────────────────────────────────────── */

interface ExpiringSession {
  id: number;
  name: string;
  expires_at: string;
  days_remaining: number;
}

interface ExportRecord {
  id: string;
  status: string;
  created_at: string | null;
  expires_at: string | null;
}

interface DataSummary {
  sessions_count: number;
  total_storage_mb: number;
  oldest_session: string | null;
  retention_policy: {
    plan_tier: string;
    raw_retention_days: number;
    sessions_expiring_soon: ExpiringSession[];
  };
  exports: ExportRecord[];
}

interface RetentionSchedule {
  retention_days: number | null;
  deletions: Array<{ date: string; sessions: Array<{ id: number; name: string }> }>;
  export_recommended: boolean;
}

/* ── Page ─────────────────────────────────────────────────── */

export default function DataPrivacyPage() {
  const [deletePassword, setDeletePassword] = useState('');
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);

  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary } = useQuery<DataSummary>({
    queryKey: ['account', 'data-summary'],
    queryFn: () => apiFetch<DataSummary>('/account/data-summary'),
    staleTime: 60_000,
  });

  const { data: schedule, isLoading: scheduleLoading } = useQuery<RetentionSchedule>({
    queryKey: ['account', 'retention-schedule'],
    queryFn: () => apiFetch<RetentionSchedule>('/account/data/retention-schedule'),
    staleTime: 60_000,
  });

  const exportMutation = useMutation({
    mutationFn: () => apiFetch<{ export_id: string }>('/account/export', { method: 'POST' }),
    onSuccess: () => refetchSummary(),
  });

  const deleteAccountMutation = useMutation({
    mutationFn: (password: string) =>
      apiFetch<{ deleted: boolean }>('/account/', {
        method: 'DELETE',
        body: JSON.stringify({ password }),
      }),
  });

  return (
    <div>
      <PageIntro title="Data & Privacy" subtitle="Manage your data, exports, and account" />

      {/* ── Your Data ───────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h3 className="font-monument text-sm text-chalk mb-4">Your Data</h3>
        {summaryLoading ? (
          <div className="animate-pulse h-24 bg-steel/10 rounded" />
        ) : summary ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="font-telemetry text-2xl text-chalk">{summary.sessions_count}</p>
              <p className="text-steel text-xs font-body">Sessions</p>
            </div>
            <div>
              <p className="font-telemetry text-2xl text-chalk">{summary.total_storage_mb} MB</p>
              <p className="text-steel text-xs font-body">Storage used</p>
            </div>
            <div>
              <p className="font-telemetry text-2xl text-chalk">
                {summary.retention_policy.raw_retention_days}d
              </p>
              <p className="text-steel text-xs font-body">Retention ({summary.retention_policy.plan_tier})</p>
            </div>
            <div>
              <p className="font-telemetry text-2xl text-chalk">{summary.oldest_session || '—'}</p>
              <p className="text-steel text-xs font-body">Oldest session</p>
            </div>
          </div>
        ) : null}
      </div>

      {/* ── Retention Schedule ──────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h3 className="font-monument text-sm text-chalk mb-4">Retention Schedule</h3>
        {scheduleLoading ? (
          <div className="animate-pulse h-20 bg-steel/10 rounded" />
        ) : schedule ? (
          <>
            {schedule.export_recommended && (
              <div className="bg-marshal-yellow/10 border border-marshal-yellow/30 rounded-md p-3 mb-4">
                <p className="text-marshal-yellow font-telemetry text-xs">
                  Some sessions expire within 30 days. Export your data before it&apos;s deleted.
                </p>
              </div>
            )}
            {schedule.deletions.length === 0 ? (
              <p className="text-steel text-sm font-body">No upcoming deletions</p>
            ) : (
              <div className="space-y-3">
                {schedule.deletions.slice(0, 10).map((group) => (
                  <div key={group.date} className="flex items-start gap-3">
                    <span className="font-telemetry text-xs text-safety-red whitespace-nowrap mt-0.5">
                      {group.date}
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {group.sessions.map((s) => (
                        <span
                          key={s.id}
                          className="bg-asphalt text-steel text-xs font-body px-2 py-0.5 rounded"
                        >
                          {s.name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* ── Export Your Data ────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h3 className="font-monument text-sm text-chalk mb-4">Export Your Data</h3>
        <p className="text-steel text-sm font-body mb-4">
          Download all your telemetry data, reports, and account information as a ZIP file.
          GPS coordinates are rounded for privacy.
        </p>
        <button
          type="button"
          onClick={() => exportMutation.mutate()}
          disabled={exportMutation.isPending}
          className="bg-gold text-white font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
        >
          {exportMutation.isPending ? 'Creating export...' : 'Request Data Export'}
        </button>
        {exportMutation.isSuccess && (
          <p className="text-acid-green text-xs font-telemetry mt-2">
            Export requested. You&apos;ll receive an email when it&apos;s ready.
          </p>
        )}

        {/* Past exports */}
        {summary?.exports && summary.exports.length > 0 && (
          <div className="mt-4">
            <p className="text-steel text-xs font-telemetry mb-2">Recent exports:</p>
            <div className="space-y-1">
              {summary.exports.map((exp) => (
                <div key={exp.id} className="flex items-center gap-3 text-xs">
                  <span className={`font-telemetry px-2 py-0.5 rounded-full ${
                    exp.status === 'completed'
                      ? 'bg-acid-green/20 text-acid-green'
                      : exp.status === 'pending'
                        ? 'bg-marshal-yellow/20 text-marshal-yellow'
                        : 'bg-steel/20 text-steel'
                  }`}>
                    {exp.status}
                  </span>
                  <span className="text-steel font-body">{exp.created_at || '—'}</span>
                  {exp.status === 'completed' && (
                    <a
                      href={`/api/v1/account/export/${exp.id}/download`}
                      className="text-acid-green hover:underline font-telemetry"
                    >
                      Download
                    </a>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Delete Account ─────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-safety-red/20 p-6">
        <h3 className="font-monument text-sm text-safety-red mb-4">Delete Account</h3>
        <p className="text-steel text-sm font-body mb-3">
          Permanently delete your account and all associated data. This action has a 30-day grace
          period during which you can cancel the deletion by logging in.
        </p>
        {!showDeleteAccount ? (
          <button
            type="button"
            onClick={() => setShowDeleteAccount(true)}
            className="bg-concrete border border-safety-red/30 text-safety-red font-telemetry text-sm px-4 py-2 rounded-md hover:bg-safety-red/10 transition"
          >
            Delete My Account
          </button>
        ) : (
          <div className="bg-asphalt border border-safety-red/30 rounded-md p-4">
            <p className="text-safety-red font-telemetry text-xs mb-3">
              Are you sure? All your data will be permanently deleted after 30 days.
            </p>
            <label htmlFor="delete-account-pw" className="sr-only">Confirm password</label>
            <input
              id="delete-account-pw"
              type="password"
              autoComplete="current-password"
              placeholder="Enter your password to confirm"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
              disabled={deleteAccountMutation.isPending}
              className="w-full bg-concrete border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm mb-3 focus:border-safety-red/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
            />
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => deleteAccountMutation.mutate(deletePassword)}
                disabled={!deletePassword || deleteAccountMutation.isPending}
                className="bg-safety-red text-chalk font-telemetry text-sm px-4 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
              >
                {deleteAccountMutation.isPending ? 'Deleting...' : 'Confirm Account Deletion'}
              </button>
              <button
                type="button"
                onClick={() => { setShowDeleteAccount(false); setDeletePassword(''); }}
                className="bg-concrete border border-steel/30 text-steel font-telemetry text-sm px-4 py-2 rounded-md hover:text-chalk transition"
              >
                Cancel
              </button>
            </div>
            {deleteAccountMutation.isSuccess && (
              <p className="text-marshal-yellow text-xs font-telemetry mt-2">
                Account scheduled for deletion. You have 30 days to cancel by logging back in.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
