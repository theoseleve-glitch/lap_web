'use client';

import Link from 'next/link';
import { useQuery, useMutation } from '@tanstack/react-query';
import { PageIntro } from '@/components/ui/PageIntro';
import { UsageDashboard } from '@/components/billing/UsageDashboard';
import { apiFetch } from '@/lib/api-client';
import { formatDateFromTimestamp } from '@/lib/format-utils';

/* ── Types ────────────────────────────────────────────────── */

interface Subscription {
  plan_tier: string;
  subscription_status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  payment_method: { brand: string; last4: string } | null;
  next_invoice_amount: number | null;
  next_invoice_currency: string | null;
}

interface Invoice {
  id: string;
  date: string | null;
  amount: number;
  currency: string;
  status: string;
  pdf_url: string | null;
}

/* ── Helpers ──────────────────────────────────────────────── */

const TIER_LABELS: Record<string, string> = {
  demo: 'Demo (Free)',
  racer: 'Racer',
  'world-class': 'World-Class',
  b2b: 'Enterprise',
};

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-acid-green/20 text-acid-green',
  trialing: 'bg-racing-purple/20 text-racing-purple',
  past_due: 'bg-marshal-yellow/20 text-marshal-yellow',
  canceled: 'bg-safety-red/20 text-safety-red',
  paused: 'bg-steel/20 text-steel',
  free: 'bg-steel/20 text-steel',
};

function formatAmount(amount: number | null, currency: string | null): string {
  if (amount === null) return '—';
  const val = amount / 100;
  const cur = (currency || 'eur').toUpperCase();
  return new Intl.NumberFormat('en', { style: 'currency', currency: cur }).format(val);
}

/* ── Page ─────────────────────────────────────────────────── */

export default function BillingPage() {
  const { data: sub, isLoading: subLoading, error: subError } = useQuery<Subscription>({
    queryKey: ['billing', 'subscription'],
    queryFn: () => apiFetch<Subscription>('/billing/subscription'),
    staleTime: 60_000,
  });

  const { data: invoiceData, isLoading: invLoading, error: invError } = useQuery<{ invoices: Invoice[]; has_more: boolean }>({
    queryKey: ['billing', 'invoices'],
    queryFn: () => apiFetch<{ invoices: Invoice[]; has_more: boolean }>('/billing/invoices'),
    staleTime: 60_000,
  });

  const portalMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ portal_url: string }>('/billing/portal', {
        method: 'POST',
        body: JSON.stringify({}),
      }),
    onSuccess: (data) => {
      window.location.href = data.portal_url;
    },
  });

  const statusClass = sub ? STATUS_STYLES[sub.subscription_status] || STATUS_STYLES.free : '';

  return (
    <div>
      <PageIntro title="Billing" subtitle="Plan, usage, and payment management" />

      {(subError || invError) && (
        <div className="mb-4 rounded-lg border border-safety-red/30 bg-safety-red/10 p-3 text-safety-red text-sm font-body">
          {subError && <p>Failed to load subscription: {(subError as Error).message}</p>}
          {invError && <p>Failed to load invoices: {(invError as Error).message}</p>}
        </div>
      )}

      {/* ── Current Plan ──────────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Current Plan</h2>
        {subLoading ? (
          <div className="animate-pulse h-20 bg-steel/10 rounded" />
        ) : sub ? (
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="font-monument text-2xl text-chalk">
                {TIER_LABELS[sub.plan_tier] || sub.plan_tier}
              </span>
              <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-telemetry ${statusClass}`}>
                {sub.subscription_status}
              </span>
              {sub.cancel_at_period_end && (
                <span className="text-xs text-marshal-yellow font-telemetry">
                  Cancels at period end
                </span>
              )}
            </div>
            <div className="text-right text-sm text-steel font-body">
              {sub.current_period_end && (
                <p>Renews: {formatDateFromTimestamp(sub.current_period_end)}</p>
              )}
              {sub.next_invoice_amount !== null && (
                <p>Next invoice: {formatAmount(sub.next_invoice_amount, sub.next_invoice_currency)}</p>
              )}
              {sub.payment_method && (
                <p className="capitalize">{sub.payment_method.brand} •••• {sub.payment_method.last4}</p>
              )}
            </div>
          </div>
        ) : null}
      </div>

      {/* ── Usage This Month ──────────────────────────────── */}
      <UsageDashboard className="mb-6" />

      {/* ── Quick Actions ─────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <Link
          href="/app/account/billing/upgrade"
          className="bg-concrete rounded-lg border border-steel/20 p-4 text-center hover:border-acid-green/40 transition-colors"
        >
          <span className="font-telemetry text-sm text-acid-green">Change Plan</span>
        </Link>
        <button
          type="button"
          onClick={() => portalMutation.mutate()}
          disabled={portalMutation.isPending || !sub?.payment_method}
          className="bg-concrete rounded-lg border border-steel/20 p-4 text-center hover:border-acid-green/40 transition-colors disabled:opacity-50"
        >
          <span className="font-telemetry text-sm text-chalk">
            {portalMutation.isPending ? 'Redirecting...' : 'Update Payment Method'}
          </span>
        </button>
        <button
          type="button"
          onClick={() => portalMutation.mutate()}
          disabled={portalMutation.isPending || sub?.subscription_status === 'free' || sub?.subscription_status === 'canceled'}
          className="bg-concrete rounded-lg border border-steel/20 p-4 text-center hover:border-safety-red/40 transition-colors disabled:opacity-50"
        >
          <span className="font-telemetry text-sm text-safety-red">Cancel Subscription</span>
        </button>
      </div>

      {portalMutation.isError && (
        <div className="mb-4 rounded-lg border border-safety-red/30 bg-safety-red/10 p-3 text-safety-red text-sm font-body">
          Failed to open billing portal: {(portalMutation.error as Error).message}
        </div>
      )}

      {/* ── Invoice History ────────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Invoice History</h2>
        {invLoading ? (
          <div className="animate-pulse space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-10 bg-steel/10 rounded" />
            ))}
          </div>
        ) : invoiceData?.invoices.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-steel font-telemetry text-xs border-b border-steel/20">
                  <th scope="col" className="pb-2">Date</th>
                  <th scope="col" className="pb-2">Amount</th>
                  <th scope="col" className="pb-2">Status</th>
                  <th scope="col" className="pb-2 text-right">PDF</th>
                </tr>
              </thead>
              <tbody>
                {invoiceData.invoices.map((inv) => (
                  <tr key={inv.id} className="border-b border-steel/10">
                    <td className="py-2 text-chalk font-body">{inv.date || '—'}</td>
                    <td className="py-2 text-chalk font-telemetry">
                      {formatAmount(inv.amount, inv.currency)}
                    </td>
                    <td className="py-2">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-telemetry ${
                        inv.status === 'paid' ? 'bg-acid-green/20 text-acid-green' :
                        inv.status === 'open' ? 'bg-marshal-yellow/20 text-marshal-yellow' :
                        'bg-steel/20 text-steel'
                      }`}>
                        {inv.status}
                      </span>
                    </td>
                    <td className="py-2 text-right">
                      {inv.pdf_url ? (
                        <a
                          href={inv.pdf_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-acid-green hover:underline font-telemetry text-xs"
                        >
                          Download
                        </a>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-steel text-sm font-body">No invoices yet</p>
        )}
      </div>
    </div>
  );
}
