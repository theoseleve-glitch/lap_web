'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { ActionButton } from '@/components/admin/ActionButton';

export default function EmailPage() {
  const queryClient = useQueryClient();
  const [resendUserId, setResendUserId] = useState('');

  const { data: stats } = useQuery({
    queryKey: ['admin-email-stats'],
    queryFn: adminApi.emailStats,
  });

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Email</h1>

      {stats && (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3">
          <MetricCard label="Total Users" value={stats.total_sent} />
          <MetricCard label="Verified" value={stats.verified} />
          <MetricCard
            label="Verification Rate"
            value={`${stats.verification_rate_pct}%`}
            status={stats.verification_rate_pct < 80 ? 'warning' : 'ok'}
          />
        </div>
      )}

      {/* Resend verification */}
      <div className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-steel">Resend Verification Email</h2>
        <div className="flex items-end gap-3">
          <div>
            <label className="text-xs text-steel">User ID</label>
            <input
              type="number"
              value={resendUserId}
              onChange={(e) => setResendUserId(e.target.value)}
              className="mt-1 block rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-chalk"
              placeholder="e.g. 42"
            />
          </div>
          {resendUserId && (
            <ActionButton
              label="Resend"
              onConfirm={async (reason) => {
                await adminApi.resendVerification(Number(resendUserId), reason);
                setResendUserId('');
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
