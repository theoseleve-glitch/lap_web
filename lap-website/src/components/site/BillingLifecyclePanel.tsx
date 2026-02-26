'use client';

import { useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { PitButton } from '@/components/ui/PitButton';
import { StampButton } from '@/components/ui/StampButton';
import { b2cPlans } from '@/data/pricing';

async function postJson<T>(url: string, body: Record<string, string>): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });

  const payload = (await response.json().catch(() => null)) as { message?: string } | null;
  if (!response.ok) {
    throw new Error(payload?.message ?? `Request failed (${response.status})`);
  }
  return payload as T;
}

export function BillingLifecyclePanel() {
  const params = useSearchParams();
  const [plan, setPlan] = useState((params.get('plan') ?? 'PERFORMANCE').toUpperCase());
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'annual'>(
    params.get('billing') === 'monthly' ? 'monthly' : 'annual',
  );
  const [email, setEmail] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [subscriptionId, setSubscriptionId] = useState('');
  const [nextPlan, setNextPlan] = useState('PRO RACER');
  const [status, setStatus] = useState('');
  const [loadingAction, setLoadingAction] = useState<'checkout' | 'portal' | 'switch' | null>(null);

  const b2cPlanNames = useMemo(
    () => b2cPlans.filter((item) => item.name !== 'STARTER').map((item) => item.name),
    [],
  );

  return (
    <section className="space-y-5">
      <article className="border border-steel/20 p-5 bg-concrete/40">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Checkout Flow</h2>
        <p className="text-sm text-steel mb-4">
          Select a B2C plan and continue directly to secure checkout.
        </p>
        <div className="grid md:grid-cols-3 gap-3 mb-4">
          <select
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          >
            {b2cPlanNames.map((planName) => (
              <option key={planName} value={planName}>
                {planName}
              </option>
            ))}
          </select>
          <select
            value={billingCycle}
            onChange={(event) => setBillingCycle(event.target.value as 'monthly' | 'annual')}
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          >
            <option value="monthly">Monthly</option>
            <option value="annual">Annual</option>
          </select>
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="Billing email"
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          />
        </div>
        <PitButton
          onClick={async () => {
            setLoadingAction('checkout');
            setStatus('');
            try {
              const result = await postJson<{ checkoutUrl: string; mode?: string }>('/api/billing/checkout', {
                plan,
                billingCycle,
                email,
                currency: 'eur',
              });
              window.location.href = result.checkoutUrl;
            } catch (error) {
              setStatus(error instanceof Error ? error.message : 'Checkout failed');
            } finally {
              setLoadingAction(null);
            }
          }}
        >
          {loadingAction === 'checkout' ? 'Preparing Checkout...' : 'Continue to Checkout'}
        </PitButton>
      </article>

      <article className="border border-steel/20 p-5 bg-concrete/40">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Billing Portal (Authenticated)</h2>
        <p className="text-steel text-sm mb-3">
          Open your invoice and payment management portal. Active auth session required.
        </p>
        <div className="grid md:grid-cols-2 gap-3 mb-3">
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="Customer email"
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          />
          <input
            value={customerId}
            onChange={(event) => setCustomerId(event.target.value)}
            placeholder="Stripe customer ID (optional)"
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          />
        </div>
        <StampButton
          onClick={async () => {
            setLoadingAction('portal');
            setStatus('');
            try {
              const result = await postJson<{ portalUrl: string }>('/api/billing/portal', {
                customerEmail: email,
                customerId,
              });
              window.location.href = result.portalUrl;
            } catch (error) {
              setStatus(error instanceof Error ? error.message : 'Portal request failed');
            } finally {
              setLoadingAction(null);
            }
          }}
        >
          {loadingAction === 'portal' ? 'Opening Portal...' : 'Open Portal'}
        </StampButton>
      </article>

      <article className="border border-steel/20 p-5 bg-concrete/40">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Plan Switch</h2>
        <p className="text-steel text-sm mb-3">Switch an active subscription and confirm proration via provider rules.</p>
        <div className="grid md:grid-cols-3 gap-3 mb-3">
          <input
            value={subscriptionId}
            onChange={(event) => setSubscriptionId(event.target.value)}
            placeholder="Subscription ID"
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          />
          <select
            value={nextPlan}
            onChange={(event) => setNextPlan(event.target.value)}
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          >
            {b2cPlanNames.map((planName) => (
              <option key={planName} value={planName}>
                {planName}
              </option>
            ))}
          </select>
          <select
            value={billingCycle}
            onChange={(event) => setBillingCycle(event.target.value as 'monthly' | 'annual')}
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          >
            <option value="monthly">Monthly</option>
            <option value="annual">Annual</option>
          </select>
        </div>
        <StampButton
          onClick={async () => {
            setLoadingAction('switch');
            setStatus('');
            try {
              const result = await postJson<{ message: string }>('/api/billing/switch', {
                subscriptionId,
                nextPlan,
                billingCycle,
              });
              setStatus(result.message || 'Plan switch accepted.');
            } catch (error) {
              setStatus(error instanceof Error ? error.message : 'Plan switch failed');
            } finally {
              setLoadingAction(null);
            }
          }}
        >
          {loadingAction === 'switch' ? 'Switching...' : 'Confirm Plan Switch'}
        </StampButton>
      </article>

      {status && <p className="text-sm text-chalk border border-steel/30 px-3 py-2">{status}</p>}
    </section>
  );
}
