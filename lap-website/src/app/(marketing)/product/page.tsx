import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { WorkflowCoverage } from '@/components/site/WorkflowCoverage';
import { StructuredData } from '@/components/site/StructuredData';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

const engineerViews = [
  {
    title: 'Key Corner Replay',
    description: 'Replay entry, apex, and exit traces to spot where the lap was won or lost.',
    image: '/images/screenshots/corner-replay.png',
  },
  {
    title: 'Full-Screen Analysis Mode',
    description: 'Review speed traces, G-G model context, and map overlays in one immersive view.',
    image: '/images/screenshots/score-overview.png',
  },
];

const strategistViews = [
  {
    title: 'Race Strategy Dashboard',
    description: 'Live operational board for stint calls, pace deltas, and pit-window decisions.',
    image: '/images/screenshots/dashboard-hero.png',
  },
  {
    title: 'Track Map + Trace Context',
    description: 'See speed traces on the track map so coaching points are instantly understandable.',
    image: '/images/screenshots/lap-table.png',
  },
];

export default function ProductPage() {
  return (
    <>
      <StructuredData
        data={{
          '@context': 'https://schema.org',
          '@type': 'TechArticle',
          headline: 'LAP: Engineer Mode + Strategist Mode',
          about: [
            'Engineer Mode — telemetry scoring, corner analysis, coaching',
            'Strategist Mode — race strategy, live monitoring, pit planning',
            'Dual-mode motorsport analytics platform',
          ],
          url: 'https://www.lap-coach.racing/product',
        }}
      />
      <PageShell
        eyebrow="Product"
        title="Two Modes. One System."
        description="Engineer Mode finds where you lose time. Strategist Mode plans how you gain it back. Data flows from one into the other."
      >
        <section className="mb-10">
          <WorkflowCoverage />
        </section>

        <section className="mb-10">
          <h2 className="font-monument text-[var(--text-h2)] mb-2 text-acid-green">Engineer Mode</h2>
          <p className="text-steel mb-4">Upload. Score. Coach. Compare. Visualize.</p>
          <div className="grid md:grid-cols-2 gap-4">
            {engineerViews.map((view) => (
              <article key={view.title} className="border border-steel/20 bg-concrete/30 p-4">
                <img src={view.image} alt={view.title} className="w-full h-52 object-cover mb-3 border border-steel/20" />
                <ReversibleCard title={view.title} description={view.description} />
              </article>
            ))}
          </div>
        </section>

        <section className="mb-10">
          <h2 className="font-monument text-[var(--text-h2)] mb-2 text-pit-orange">Strategist Mode</h2>
          <p className="text-steel mb-4">Control Room. Live Monitoring. Pit Planning. Incidents.</p>
          <div className="grid md:grid-cols-2 gap-4">
            {strategistViews.map((view) => (
              <article key={view.title} className="border border-steel/20 bg-concrete/30 p-4">
                <img src={view.image} alt={view.title} className="w-full h-52 object-cover mb-3 border border-steel/20" />
                <ReversibleCard title={view.title} description={view.description} />
              </article>
            ))}
          </div>
        </section>

        <section className="mb-10 border border-steel/20 bg-concrete/20 p-5">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">How They Connect</h2>
          <p className="text-steel text-sm leading-relaxed">
            Engineer Mode produces per-lap scores, corner diagnostics, and coaching
            recommendations. That data feeds directly into Strategist Mode, where
            stint plans, pit windows, and live pace deltas are built on top of the
            same underlying telemetry. One upload powers both workflows — analysis
            flows into strategy without re-importing or switching tools.
          </p>
        </section>

        <section className="mt-10 border border-steel/20 p-5 bg-concrete/20">
          <h2 className="font-monument text-[var(--text-h3)] mb-2">Next Actions</h2>
          <div className="flex flex-wrap gap-3">
            <Link href="/demo" className="border border-pit-orange px-4 py-2 text-sm">
              Try Demo
            </Link>
            <Link href="/pricing" className="border border-steel/30 px-4 py-2 text-sm">
              Compare Plans
            </Link>
            <Link href="/contact" className="border border-steel/30 px-4 py-2 text-sm">
              Contact Sales
            </Link>
          </div>
        </section>
      </PageShell>
    </>
  );
}
