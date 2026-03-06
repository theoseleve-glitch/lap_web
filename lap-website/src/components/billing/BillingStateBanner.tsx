'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '@/lib/api-client';

interface SubscriptionStatus {
  plan_tier: string;
  subscription_status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

interface BannerConfig {
  message: string;
  cta: string;
  href: string;
  style: string;
  borderStyle: string;
}

const BANNER_MAP: Record<string, BannerConfig> = {
  past_due: {
    message: 'Your payment is past due. Please update your payment method to avoid service interruption.',
    cta: 'Update Payment',
    href: '/app/account/billing',
    style: 'bg-marshal-yellow/10 text-marshal-yellow',
    borderStyle: 'border-marshal-yellow/30',
  },
  unpaid: {
    message: 'Your subscription payment has failed. Access is restricted until payment is resolved.',
    cta: 'Resolve Payment',
    href: '/app/account/billing',
    style: 'bg-safety-red/10 text-safety-red',
    borderStyle: 'border-safety-red/30',
  },
  canceled: {
    message: 'Your subscription has been canceled. You can still access your data during the grace period.',
    cta: 'Resubscribe',
    href: '/pricing',
    style: 'bg-safety-red/10 text-safety-red',
    borderStyle: 'border-safety-red/30',
  },
  paused: {
    message: 'Your subscription is paused. Resume to upload new sessions and generate reports.',
    cta: 'Resume Subscription',
    href: '/app/account/billing',
    style: 'bg-steel/10 text-steel',
    borderStyle: 'border-steel/30',
  },
};

/**
 * App-wide billing state banner.
 *
 * Fetches subscription status and renders a dismissible warning bar when
 * the subscription is in a non-healthy state (past_due, unpaid, canceled,
 * paused). Renders nothing for active/trialing/free states.
 */
export function BillingStateBanner() {
  const { data: sub } = useQuery<SubscriptionStatus>({
    queryKey: ['billing', 'subscription'],
    queryFn: () => apiFetch<SubscriptionStatus>('/billing/subscription'),
    staleTime: 5 * 60_000, // 5 min — avoids hammering on every page nav
    retry: false,
  });

  if (!sub) return null;

  const config = BANNER_MAP[sub.subscription_status];
  if (!config) return null;

  // For canceled: show period end date if available
  let message = config.message;
  if (sub.subscription_status === 'canceled' && sub.current_period_end) {
    const endDate = new Date(sub.current_period_end).toLocaleDateString();
    message = `Your subscription has been canceled. Access continues until ${endDate}.`;
  }

  return (
    <div
      role="alert"
      className={`flex items-center justify-between gap-4 rounded-lg border px-4 py-3 text-sm font-body ${config.style} ${config.borderStyle}`}
    >
      <p className="min-w-0">{message}</p>
      <Link
        href={config.href}
        className="shrink-0 rounded-md bg-chalk/10 px-3 py-1.5 text-xs font-telemetry transition-colors hover:bg-chalk/20"
      >
        {config.cta}
      </Link>
    </div>
  );
}
