'use client';

import { useState } from 'react';
import { PitButton } from '@/components/ui/PitButton';
import { StampButton } from '@/components/ui/StampButton';

async function postJson<T>(url: string, body: Record<string, string>): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function BillingLifecyclePanel() {
  const [plan, setPlan] = useState('PERFORMANCE');
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'annual'>('annual');
  const [email, setEmail] = useState('');
  const [subscriptionId, setSubscriptionId] = useState('');
  const [nextPlan, setNextPlan] = useState('PRO RACER');
  const [status, setStatus] = useState('');

  return (
    <section className="space-y-5">
      <article className="border border-steel/20 p-5 bg-concrete/40">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Checkout</h2>
        <div className="grid md:grid-cols-3 gap-3 mb-4">
          <input
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
            placeholder="Plan"
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          />
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
            try {
              const result = await postJson<{ checkoutUrl: string }>('/api/billing/checkout', {
                plan,
                billingCycle,
                email,
                currency: 'EUR',
              });
              window.location.href = result.checkoutUrl;
            } catch (error) {
              setStatus(error instanceof Error ? error.message : 'Checkout failed');
            }
          }}
        >
          Start Checkout
        </PitButton>
      </article>

      <article className="border border-steel/20 p-5 bg-concrete/40">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Billing Portal</h2>
        <p className="text-steel text-sm mb-3">
          Open portal access for invoices, payment methods, and VAT profile updates.
        </p>
        <StampButton
          onClick={async () => {
            try {
              const result = await postJson<{ portalUrl: string }>('/api/billing/portal', {
                customerEmail: email,
              });
              window.location.href = result.portalUrl;
            } catch (error) {
              setStatus(error instanceof Error ? error.message : 'Portal request failed');
            }
          }}
        >
          Open Portal
        </StampButton>
      </article>

      <article className="border border-steel/20 p-5 bg-concrete/40">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Plan Switch</h2>
        <div className="grid md:grid-cols-2 gap-3 mb-3">
          <input
            value={subscriptionId}
            onChange={(event) => setSubscriptionId(event.target.value)}
            placeholder="Subscription ID"
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          />
          <input
            value={nextPlan}
            onChange={(event) => setNextPlan(event.target.value)}
            placeholder="Next plan"
            className="bg-asphalt border border-steel/30 px-3 py-2 text-sm"
          />
        </div>
        <StampButton
          onClick={async () => {
            try {
              const result = await postJson<{ message: string }>('/api/billing/switch', {
                subscriptionId,
                nextPlan,
              });
              setStatus(result.message);
            } catch (error) {
              setStatus(error instanceof Error ? error.message : 'Plan switch failed');
            }
          }}
        >
          Switch Plan
        </StampButton>
      </article>

      {status && <p className="text-sm text-steel">{status}</p>}
    </section>
  );
}
