import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';

const articles = [
  {
    slug: 'telemetry-corner-analysis',
    title: 'Telemetry Corner Analysis for Kart Drivers',
    intent: 'corner telemetry analysis karting',
  },
  {
    slug: 'session-vs-session-comparison',
    title: 'How Session-vs-Session Comparison Improves Race Pace',
    intent: 'session vs session motorsport analytics',
  },
  {
    slug: 'race-strategy-dashboard',
    title: 'Building a Race Strategy Dashboard for Endurance Teams',
    intent: 'race strategy dashboard endurance',
  },
];

export default function InsightsPage() {
  return (
    <PageShell
      eyebrow="SEO Content"
      title="Feature Intent Content"
      description="Long-tail content hubs aligned to telemetry analysis search intent."
    >
      <section className="space-y-4">
        {articles.map((article) => (
          <article key={article.slug} className="border border-steel/20 p-4 bg-concrete/30">
            <h2 className="font-monument text-[var(--text-h3)] mb-2">{article.title}</h2>
            <p className="text-steel text-sm mb-3">Keyword intent: {article.intent}</p>
            <Link href={`/product#${article.slug}`} className="text-sm border border-steel/30 px-3 py-1">
              Explore Related Product Module
            </Link>
          </article>
        ))}
      </section>
    </PageShell>
  );
}
