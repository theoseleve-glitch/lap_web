'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Suspense } from 'react';
import { JsonLd } from '@/components/seo/JsonLd';
import { BillingLifecyclePanel } from '@/components/site/BillingLifecyclePanel';
import { PageIntro } from '@/components/ui/PageIntro';

function AuthGate({ children }: { children: React.ReactNode }) {
  const [hasSession, setHasSession] = useState<boolean | null>(null);

  useEffect(() => {
    // Check for auth token — billing operations require a valid session
    const token =
      typeof window !== 'undefined' &&
      (document.cookie.includes('lap_refresh') || sessionStorage.getItem('lap_auth'));
    setHasSession(!!token);
  }, []);

  if (hasSession === null) {
    return (
      <div className="flex items-center justify-center h-32">
        <div className="w-6 h-6 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  if (!hasSession) {
    return (
      <div className="border border-steel/20 bg-concrete/30 p-8 text-center">
        <h2 className="font-monument text-[var(--text-h3)] mb-3">Sign in to manage billing</h2>
        <p className="text-steel text-sm mb-6">
          You need an active account to access checkout, subscription management, and invoice
          history.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Link
            href="/login"
            className="border border-pit-orange text-pit-orange px-4 py-2 text-sm font-telemetry uppercase tracking-wider hover:bg-pit-orange/10 transition-colors"
          >
            Sign In
          </Link>
          <Link
            href="/register"
            className="border border-steel/30 text-steel px-4 py-2 text-sm font-telemetry uppercase tracking-wider hover:text-chalk transition-colors"
          >
            Create Account
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

export default function BillingPage() {
  return (
    <>
    <JsonLd pathname="/billing" />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Subscription"
        title="Billing & Subscription Management"
        subtitle="Manage your plan, update payment details, and access invoice history."
      />
      <AuthGate>
        <section className="mb-8">
          <Suspense
            fallback={<p className="text-steel text-sm">Loading billing panel...</p>}
          >
            <BillingLifecyclePanel />
          </Suspense>
        </section>
      </AuthGate>

      <section className="grid md:grid-cols-2 gap-4">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">VAT and Currency</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>Default currency is EUR with provider-side localisation support.</li>
            <li>VAT ID is collected during checkout and validated automatically.</li>
            <li>Tax-inclusive and tax-exclusive totals appear on all invoices.</li>
          </ul>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Invoice &amp; Payment</h2>
          <ul className="space-y-2 text-sm text-steel">
            <li>Invoices are issued automatically after each successful payment.</li>
            <li>Access all invoices through the billing portal above.</li>
            <li>Failed payments are retried per Stripe&rsquo;s dunning schedule.</li>
          </ul>
        </article>
      </section>

      <div className="mt-8 text-center text-xs text-steel font-body space-x-4">
        <Link href="/pricing" className="hover:text-chalk transition">
          Compare Plans
        </Link>
        <Link href="/contact" className="hover:text-chalk transition">
          Billing Support
        </Link>
      </div>
    </main>
    </>
  );
}
