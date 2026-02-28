'use client';

import { useState, useId } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { PageHeader } from '@/components/app';
import { apiFetch } from '@/lib/api-client';

/* ── Types ────────────────────────────────────────────────── */

interface MeProfile {
  id: number;
  email: string;
  display_name: string;
  totp_enabled?: boolean;
}

interface TotpSetupResponse {
  secret: string;
  provisioning_uri: string;
  qr_code?: string;
}

interface TotpConfirmResponse {
  enabled: boolean;
  backup_codes: string[];
}

interface BackupCodesResponse {
  backup_codes: string[];
}

interface Session {
  id: string;
  user_agent: string;
  ip_address: string;
  created_at: string;
  last_used_at: string;
  is_current: boolean;
}

interface OAuthConnection {
  provider: string;
  provider_user_id: string;
  connected_at: string;
}

/* ── Helpers ──────────────────────────────────────────────── */

function parseUserAgent(ua: string): string {
  if (!ua) return 'Unknown';
  if (ua.includes('Chrome')) return 'Chrome';
  if (ua.includes('Firefox')) return 'Firefox';
  if (ua.includes('Safari')) return 'Safari';
  if (ua.includes('Edge')) return 'Edge';
  return ua.slice(0, 40);
}

function formatRelative(iso: string): string {
  if (!iso) return '---';
  const d = new Date(iso);
  const now = Date.now();
  const diff = now - d.getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}

const PROVIDER_LABELS: Record<string, string> = {
  google: 'Google',
  github: 'GitHub',
};

/* ── 2FA Step Type ────────────────────────────────────────── */

type TwoFaStep = 'idle' | 'qr' | 'verify' | 'backup';

/* ── Page ─────────────────────────────────────────────────── */

export default function SecurityPage() {
  const queryClient = useQueryClient();
  const fieldId = useId();

  /* ── State ────────────────────────────────────────── */
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [twoFaStep, setTwoFaStep] = useState<TwoFaStep>('idle');
  const [totpSetup, setTotpSetup] = useState<TotpSetupResponse | null>(null);
  const [totpCode, setTotpCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [disablePassword, setDisablePassword] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [showDisable, setShowDisable] = useState(false);
  const [regenPassword, setRegenPassword] = useState('');
  const [regenCode, setRegenCode] = useState('');
  const [showRegen, setShowRegen] = useState(false);

  /* ── Queries ──────────────────────────────────────── */
  const { data: me, isLoading: meLoading } = useQuery<MeProfile>({
    queryKey: ['account', 'me'],
    queryFn: () => apiFetch<MeProfile>('/me'),
    staleTime: 60_000,
  });

  const { data: sessions, isLoading: sessionsLoading } = useQuery<Session[]>({
    queryKey: ['account', 'sessions'],
    queryFn: () => apiFetch<Session[]>('/account/sessions'),
    staleTime: 30_000,
  });

  const { data: connections, isLoading: connectionsLoading } = useQuery<OAuthConnection[]>({
    queryKey: ['account', 'connections'],
    queryFn: () => apiFetch<OAuthConnection[]>('/account/connections'),
    staleTime: 60_000,
  });

  /* ── Mutations ────────────────────────────────────── */
  const changePasswordMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ message: string }>('/account/change-password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      }),
    onSuccess: () => {
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    },
  });

  const setupTotpMutation = useMutation({
    mutationFn: () =>
      apiFetch<TotpSetupResponse>('/account/2fa/setup', { method: 'POST' }),
    onSuccess: (data) => {
      setTotpSetup(data);
      setTwoFaStep('qr');
    },
  });

  const confirmTotpMutation = useMutation({
    mutationFn: () =>
      apiFetch<TotpConfirmResponse>('/account/2fa/confirm', {
        method: 'POST',
        body: JSON.stringify({ code: totpCode }),
      }),
    onSuccess: (data) => {
      setBackupCodes(data.backup_codes);
      setTwoFaStep('backup');
      setTotpCode('');
      queryClient.invalidateQueries({ queryKey: ['account', 'me'] });
    },
  });

  const disableTotpMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ disabled: boolean }>('/account/2fa/disable', {
        method: 'POST',
        body: JSON.stringify({ password: disablePassword, code: disableCode }),
      }),
    onSuccess: () => {
      setShowDisable(false);
      setDisablePassword('');
      setDisableCode('');
      queryClient.invalidateQueries({ queryKey: ['account', 'me'] });
    },
  });

  const regenBackupMutation = useMutation({
    mutationFn: () =>
      apiFetch<BackupCodesResponse>('/account/2fa/backup-codes', {
        method: 'POST',
        body: JSON.stringify({ password: regenPassword, code: regenCode }),
      }),
    onSuccess: (data) => {
      setBackupCodes(data.backup_codes);
      setShowRegen(false);
      setRegenPassword('');
      setRegenCode('');
      setTwoFaStep('backup');
    },
  });

  const revokeSessionMutation = useMutation({
    mutationFn: (sessionId: string) =>
      apiFetch<{ revoked: boolean }>(`/account/sessions/${sessionId}`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['account', 'sessions'] });
    },
  });

  const revokeAllMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ message: string }>('/account/sessions/revoke-all', {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['account', 'sessions'] });
    },
  });

  const unlinkMutation = useMutation({
    mutationFn: (provider: string) =>
      apiFetch<{ unlinked: string }>(`/account/connections/${provider}`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['account', 'connections'] });
    },
  });

  const passwordsMatch = newPassword === confirmPassword;
  const canSubmitPassword = currentPassword && newPassword && confirmPassword && passwordsMatch;
  const totpEnabled = me?.totp_enabled === true;

  return (
    <div>
      <PageHeader title="Security" subtitle="Password, two-factor authentication, and active sessions" />

      {/* ── Change Password ───────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Change Password</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmitPassword) changePasswordMutation.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor={`${fieldId}-cur-pw`} className="block text-steel text-xs font-telemetry mb-1">Current Password</label>
            <input
              id={`${fieldId}-cur-pw`}
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor={`${fieldId}-new-pw`} className="block text-steel text-xs font-telemetry mb-1">New Password</label>
            <input
              id={`${fieldId}-new-pw`}
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor={`${fieldId}-confirm-pw`} className="block text-steel text-xs font-telemetry mb-1">Confirm New Password</label>
            <input
              id={`${fieldId}-confirm-pw`}
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none"
            />
            {confirmPassword && !passwordsMatch && (
              <p className="text-safety-red text-xs font-telemetry mt-1">Passwords do not match</p>
            )}
          </div>

          {changePasswordMutation.isError && (
            <p className="text-safety-red text-xs font-telemetry">
              {(changePasswordMutation.error as Error).message}
            </p>
          )}
          {changePasswordMutation.isSuccess && (
            <p className="text-acid-green text-xs font-telemetry">Password updated successfully</p>
          )}

          <button
            type="submit"
            disabled={!canSubmitPassword || changePasswordMutation.isPending}
            className="bg-acid-green text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
          >
            {changePasswordMutation.isPending ? 'Updating...' : 'Update Password'}
          </button>
        </form>
      </div>

      {/* ── Two-Factor Authentication ─────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Two-Factor Authentication</h2>
        {meLoading ? (
          <div className="animate-pulse h-16 bg-steel/10 rounded" />
        ) : twoFaStep === 'idle' ? (
          totpEnabled ? (
            /* 2FA is currently enabled */
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-telemetry bg-acid-green/20 text-acid-green">
                  Enabled
                </span>
                <p className="text-steel text-sm font-body">
                  Your account is protected with two-factor authentication.
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setShowRegen(true)}
                  className="bg-concrete border border-steel/30 text-steel font-telemetry text-sm px-4 py-2 rounded-md hover:text-chalk transition"
                >
                  Regenerate Backup Codes
                </button>
                <button
                  type="button"
                  onClick={() => setShowDisable(true)}
                  className="bg-concrete border border-safety-red/30 text-safety-red font-telemetry text-sm px-4 py-2 rounded-md hover:bg-safety-red/10 transition"
                >
                  Disable 2FA
                </button>
              </div>

              {/* Regenerate backup codes form */}
              {showRegen && (
                <div className="bg-asphalt border border-steel/30 rounded-md p-4 space-y-3">
                  <p className="text-chalk text-sm font-telemetry">Regenerate Backup Codes</p>
                  <p className="text-steel text-xs font-body">
                    Enter your password and a current 2FA code to generate new backup codes. Previous codes will be invalidated.
                  </p>
                  <div>
                    <label htmlFor={`${fieldId}-regen-pw`} className="block text-steel text-xs font-telemetry mb-1">Password</label>
                    <input
                      id={`${fieldId}-regen-pw`}
                      type="password"
                      autoComplete="current-password"
                      value={regenPassword}
                      onChange={(e) => setRegenPassword(e.target.value)}
                      className="w-full bg-concrete border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor={`${fieldId}-regen-code`} className="block text-steel text-xs font-telemetry mb-1">2FA Code</label>
                    <input
                      id={`${fieldId}-regen-code`}
                      type="text"
                      inputMode="numeric"
                      maxLength={6}
                      value={regenCode}
                      onChange={(e) => setRegenCode(e.target.value.replace(/\D/g, ''))}
                      placeholder="000000"
                      className="w-full bg-concrete border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none"
                    />
                  </div>
                  {regenBackupMutation.isError && (
                    <p className="text-safety-red text-xs font-telemetry">
                      {(regenBackupMutation.error as Error).message}
                    </p>
                  )}
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => regenBackupMutation.mutate()}
                      disabled={!regenPassword || regenCode.length !== 6 || regenBackupMutation.isPending}
                      className="bg-acid-green text-asphalt font-telemetry text-sm px-4 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
                    >
                      {regenBackupMutation.isPending ? 'Generating...' : 'Generate New Codes'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowRegen(false); setRegenPassword(''); setRegenCode(''); }}
                      className="bg-concrete border border-steel/30 text-steel font-telemetry text-sm px-4 py-2 rounded-md hover:text-chalk transition"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Disable 2FA form */}
              {showDisable && (
                <div className="bg-asphalt border border-safety-red/30 rounded-md p-4 space-y-3">
                  <p className="text-safety-red text-sm font-telemetry">Disable Two-Factor Authentication</p>
                  <p className="text-steel text-xs font-body">
                    Enter your password and a current 2FA code to disable two-factor authentication.
                  </p>
                  <div>
                    <label htmlFor={`${fieldId}-disable-pw`} className="block text-steel text-xs font-telemetry mb-1">Password</label>
                    <input
                      id={`${fieldId}-disable-pw`}
                      type="password"
                      autoComplete="current-password"
                      value={disablePassword}
                      onChange={(e) => setDisablePassword(e.target.value)}
                      className="w-full bg-concrete border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label htmlFor={`${fieldId}-disable-code`} className="block text-steel text-xs font-telemetry mb-1">2FA Code</label>
                    <input
                      id={`${fieldId}-disable-code`}
                      type="text"
                      inputMode="numeric"
                      maxLength={6}
                      value={disableCode}
                      onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ''))}
                      placeholder="000000"
                      className="w-full bg-concrete border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none"
                    />
                  </div>
                  {disableTotpMutation.isError && (
                    <p className="text-safety-red text-xs font-telemetry">
                      {(disableTotpMutation.error as Error).message}
                    </p>
                  )}
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => disableTotpMutation.mutate()}
                      disabled={!disablePassword || disableCode.length !== 6 || disableTotpMutation.isPending}
                      className="bg-safety-red text-chalk font-telemetry text-sm px-4 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
                    >
                      {disableTotpMutation.isPending ? 'Disabling...' : 'Disable 2FA'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowDisable(false); setDisablePassword(''); setDisableCode(''); }}
                      className="bg-concrete border border-steel/30 text-steel font-telemetry text-sm px-4 py-2 rounded-md hover:text-chalk transition"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* 2FA is not enabled */
            <div className="space-y-3">
              <p className="text-steel text-sm font-body">
                Add an extra layer of security to your account by enabling two-factor authentication with an authenticator app.
              </p>
              {setupTotpMutation.isError && (
                <p className="text-safety-red text-xs font-telemetry">
                  {(setupTotpMutation.error as Error).message}
                </p>
              )}
              <button
                type="button"
                onClick={() => setupTotpMutation.mutate()}
                disabled={setupTotpMutation.isPending}
                className="bg-acid-green text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
              >
                {setupTotpMutation.isPending ? 'Setting up...' : 'Enable 2FA'}
              </button>
            </div>
          )
        ) : twoFaStep === 'qr' ? (
          /* Step 1: Show QR code */
          <div className="space-y-4">
            <p className="text-chalk text-sm font-body">
              Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.):
            </p>
            <div className="flex justify-center">
              {totpSetup?.qr_code ? (
                <img
                  src={totpSetup.qr_code}
                  alt="2FA QR Code"
                  className="w-48 h-48 rounded-lg bg-white p-2"
                />
              ) : (
                <div className="w-48 h-48 bg-asphalt border border-steel/30 rounded-lg flex items-center justify-center">
                  <p className="text-steel text-xs font-body text-center px-4">
                    QR code not available. Use the manual entry below.
                  </p>
                </div>
              )}
            </div>
            <div className="bg-asphalt rounded-md p-3">
              <p className="text-steel text-xs font-telemetry mb-1">Manual entry key:</p>
              <code className="text-acid-green font-telemetry text-sm break-all select-all">
                {totpSetup?.secret}
              </code>
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setTwoFaStep('verify')}
                className="bg-acid-green text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition"
              >
                Next: Enter Code
              </button>
              <button
                type="button"
                onClick={() => { setTwoFaStep('idle'); setTotpSetup(null); }}
                className="bg-concrete border border-steel/30 text-steel font-telemetry text-sm px-4 py-2 rounded-md hover:text-chalk transition"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : twoFaStep === 'verify' ? (
          /* Step 2: Verify code */
          <div className="space-y-4">
            <p className="text-chalk text-sm font-body">
              Enter the 6-digit code from your authenticator app to verify setup:
            </p>
            <div>
              <label htmlFor={`${fieldId}-totp`} className="block text-steel text-xs font-telemetry mb-1">Verification Code</label>
              <input
                id={`${fieldId}-totp`}
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                placeholder="000000"
                autoFocus
                className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none tracking-[0.3em] text-center text-lg"
              />
            </div>
            {confirmTotpMutation.isError && (
              <p className="text-safety-red text-xs font-telemetry">
                {(confirmTotpMutation.error as Error).message}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => confirmTotpMutation.mutate()}
                disabled={totpCode.length !== 6 || confirmTotpMutation.isPending}
                className="bg-acid-green text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition disabled:opacity-50"
              >
                {confirmTotpMutation.isPending ? 'Verifying...' : 'Verify & Enable'}
              </button>
              <button
                type="button"
                onClick={() => { setTwoFaStep('qr'); setTotpCode(''); }}
                className="bg-concrete border border-steel/30 text-steel font-telemetry text-sm px-4 py-2 rounded-md hover:text-chalk transition"
              >
                Back
              </button>
            </div>
          </div>
        ) : twoFaStep === 'backup' ? (
          /* Step 3: Backup codes */
          <div className="space-y-4">
            <div className="bg-marshal-yellow/10 border border-marshal-yellow/30 rounded-md p-3">
              <p className="text-marshal-yellow font-telemetry text-xs">
                Save these backup codes in a secure place. Each code can only be used once. You will not be able to view them again.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {backupCodes.map((code, i) => (
                <div
                  key={i}
                  className="bg-asphalt rounded-md px-3 py-2 text-center"
                >
                  <code className="text-chalk font-telemetry text-sm select-all">{code}</code>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => {
                setTwoFaStep('idle');
                setBackupCodes([]);
                setTotpSetup(null);
              }}
              className="bg-acid-green text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition"
            >
              I&apos;ve Saved These Codes
            </button>
          </div>
        ) : null}
      </div>

      {/* ── Active Sessions ───────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-monument text-sm text-chalk">Active Sessions</h2>
          {sessions && sessions.length > 1 && (
            <button
              type="button"
              onClick={() => revokeAllMutation.mutate()}
              disabled={revokeAllMutation.isPending}
              className="bg-concrete border border-safety-red/30 text-safety-red font-telemetry text-xs px-3 py-1.5 rounded-md hover:bg-safety-red/10 transition disabled:opacity-50"
            >
              {revokeAllMutation.isPending ? 'Revoking...' : 'Revoke All Others'}
            </button>
          )}
        </div>
        {sessionsLoading ? (
          <div className="animate-pulse space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 bg-steel/10 rounded" />
            ))}
          </div>
        ) : sessions && sessions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-steel font-telemetry text-xs border-b border-steel/20">
                  <th scope="col" className="pb-2">Browser</th>
                  <th scope="col" className="pb-2">IP Address</th>
                  <th scope="col" className="pb-2">Last Active</th>
                  <th scope="col" className="pb-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((session) => (
                  <tr key={session.id} className="border-b border-steel/10">
                    <td className="py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="text-chalk font-body text-sm">
                          {parseUserAgent(session.user_agent)}
                        </span>
                        {session.is_current && (
                          <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-telemetry bg-acid-green/20 text-acid-green">
                            Current
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 text-steel font-telemetry text-xs">
                      {session.ip_address}
                    </td>
                    <td className="py-2.5 text-steel font-body text-xs">
                      {formatRelative(session.last_used_at)}
                    </td>
                    <td className="py-2.5 text-right">
                      {!session.is_current && (
                        <button
                          type="button"
                          onClick={() => revokeSessionMutation.mutate(session.id)}
                          disabled={revokeSessionMutation.isPending}
                          className="text-safety-red text-xs font-telemetry hover:underline disabled:opacity-50"
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-steel text-sm font-body">No active sessions</p>
        )}
        {revokeAllMutation.isSuccess && (
          <p className="text-acid-green text-xs font-telemetry mt-2">All other sessions revoked</p>
        )}
      </div>

      {/* ── Connected Accounts ────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Connected Accounts</h2>
        {connectionsLoading ? (
          <div className="animate-pulse space-y-2">
            <div className="h-12 bg-steel/10 rounded" />
            <div className="h-12 bg-steel/10 rounded" />
          </div>
        ) : connections && connections.length > 0 ? (
          <div className="space-y-3">
            {connections.map((conn) => (
              <div
                key={conn.provider}
                className="flex items-center justify-between bg-asphalt rounded-md p-3"
              >
                <div>
                  <p className="text-chalk text-sm font-body">
                    {PROVIDER_LABELS[conn.provider] || conn.provider}
                  </p>
                  <p className="text-steel text-xs font-body">
                    Connected {new Date(conn.connected_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => unlinkMutation.mutate(conn.provider)}
                  disabled={unlinkMutation.isPending}
                  className="text-safety-red text-xs font-telemetry hover:underline disabled:opacity-50"
                >
                  Unlink
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-steel text-sm font-body">No connected accounts</p>
            <p className="text-steel text-xs font-body">
              You can connect Google or GitHub from the login page to enable single sign-on.
            </p>
          </div>
        )}
        {unlinkMutation.isError && (
          <p className="text-safety-red text-xs font-telemetry mt-2">
            {(unlinkMutation.error as Error).message}
          </p>
        )}
      </div>
    </div>
  );
}
