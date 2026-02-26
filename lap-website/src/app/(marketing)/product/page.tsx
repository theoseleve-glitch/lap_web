import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { WorkflowCoverage } from '@/components/site/WorkflowCoverage';
import { claimsByStatus, getClaimsForSurface } from '@/data/claim-registry';
import { StructuredData } from '@/components/site/StructuredData';

export default function ProductPage() {
  const productClaims = getClaimsForSurface('product');

  return (
    <>
      <StructuredData
        data={{
          '@context': 'https://schema.org',
          '@type': 'TechArticle',
          headline: 'LAP Product Workflow Coverage',
          about: ['Telemetry analysis', 'Motorsport analytics workflow'],
          url: 'https://lap.racing/product',
        }}
      />
      <PageShell
        eyebrow="Product Workflow Coverage"
        title="From Upload to Strategy: End-to-End Workflow Modules"
        description="This page documents implemented workflow modules and clearly marks enterprise and roadmap capabilities."
      >
        <section className="mb-10">
          <WorkflowCoverage />
        </section>

      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">Claim Registry Mapping</h2>
        <div className="grid md:grid-cols-2 gap-4">
          {productClaims.map((claim) => (
            <article key={claim.id} className="border border-steel/20 p-4 bg-concrete/30">
              <p className="font-body text-chalk mb-2">{claim.claim}</p>
              <p className="text-sm text-steel">Capability: {claim.capability}</p>
              <p className="text-xs text-steel/80 mt-2">Status: {claim.status}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="grid md:grid-cols-3 gap-4">
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">Available Now</h2>
          <ul className="space-y-2 text-sm text-steel">
            {claimsByStatus.available_now.map((claim) => (
              <li key={claim.id}>{claim.capability}</li>
            ))}
          </ul>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">Enterprise / On Request</h2>
          <ul className="space-y-2 text-sm text-steel">
            {claimsByStatus.enterprise_on_request.map((claim) => (
              <li key={claim.id}>{claim.capability}</li>
            ))}
          </ul>
        </article>
        <article className="border border-steel/20 p-4">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">Roadmap</h2>
          <ul className="space-y-2 text-sm text-steel">
            {claimsByStatus.roadmap.map((claim) => (
              <li key={claim.id}>{claim.capability}</li>
            ))}
          </ul>
        </article>
      </section>

        <section className="mt-10 border border-steel/20 p-5 bg-concrete/20">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Next Actions</h2>
          <div className="flex flex-wrap gap-3">
            <Link href="/demo" className="border border-pit-orange px-4 py-2 text-sm">
              Book Demo
            </Link>
            <Link href="/pricing" className="border border-steel/30 px-4 py-2 text-sm">
              Compare Plans
            </Link>
            <Link href="/waitlist" className="border border-steel/30 px-4 py-2 text-sm">
              Join Waitlist
            </Link>
          </div>
        </section>
      </PageShell>
    </>
  );
}
