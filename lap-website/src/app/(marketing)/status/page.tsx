import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/status');

interface LiveStatus {
  indicator: 'none' | 'minor' | 'major' | 'critical';
  description: string;
  source: string;
  updatedAt: string;
}

async function getLiveStatus(): Promise<LiveStatus> {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000';
  try {
    const response = await fetch(`${baseUrl}/api/status`, {
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('Failed to load status');
    return (await response.json()) as LiveStatus;
  } catch {
    return {
      indicator: 'none',
      description: 'Operational',
      source: 'fallback',
      updatedAt: new Date().toISOString(),
    };
  }
}

export default async function StatusPage() {
  const liveStatus = await getLiveStatus();

  return (
    <>
    <JsonLd pathname="/status" />
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Operations"
        title="Status and SLA Definitions"
        subtitle="Operational status source, uptime expectations, and support SLA definitions."
      />
      <section className="grid md:grid-cols-2 gap-4 mb-8">
        <article className="border border-steel/20 p-4 bg-concrete/30">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Live Platform Status</h2>
          <p className="text-sm text-steel mb-2">
            Indicator: <span className="text-chalk uppercase">{liveStatus.indicator}</span>
          </p>
          <p className="text-sm text-steel mb-2">{liveStatus.description}</p>
          <p className="text-xs text-steel">Last update: {new Date(liveStatus.updatedAt).toLocaleString()}</p>
          <Link
            href="https://status.lap.racing"
            className="inline-block mt-3 text-sm border border-steel/30 px-3 py-1 hover:border-chalk"
          >
            status.lap.racing
          </Link>
        </article>
        <ReversibleCard
          title="Uptime Targets"
          description="Core target: 99.9% monthly availability. Maintenance windows are announced in advance with impact scope and ETA updates."
        />
      </section>

      <section className="border border-steel/20 p-4 mb-8">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">SLA Definitions</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-concrete">
              <th className="text-left p-2 border border-steel/20">Tier</th>
              <th className="text-left p-2 border border-steel/20">P1 Response</th>
              <th className="text-left p-2 border border-steel/20">P2 Response</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="p-2 border border-steel/20">Standard</td>
              <td className="p-2 border border-steel/20">1 business day</td>
              <td className="p-2 border border-steel/20">2 business days</td>
            </tr>
            <tr>
              <td className="p-2 border border-steel/20">Premium</td>
              <td className="p-2 border border-steel/20">4 hours</td>
              <td className="p-2 border border-steel/20">1 business day</td>
            </tr>
            <tr>
              <td className="p-2 border border-steel/20">Enterprise</td>
              <td className="p-2 border border-steel/20">Contract defined</td>
              <td className="p-2 border border-steel/20">Contract defined</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section className="border border-steel/20 p-4">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Auditability</h2>
        <p className="text-sm text-steel">
          Every pipeline job can be traced by job ID, source upload, processing stage transitions,
          and report publication timestamp for compliance audits.
        </p>
      </section>
    </main>
    </>
  );
}
