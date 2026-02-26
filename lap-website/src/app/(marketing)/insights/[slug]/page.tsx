import { notFound } from 'next/navigation';
import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { insightEntries } from '@/data/insights-cms';

export default function InsightDetailPage({ params }: { params: { slug: string } }) {
  const article = insightEntries.find((item) => item.slug === params.slug);
  if (!article) {
    notFound();
  }

  return (
    <PageShell eyebrow="Insight Detail" title={article.title} description={article.summary}>
      <article className="border border-steel/20 bg-concrete/30 p-5">
        <p className="text-steel text-sm mb-4">Keyword intent: {article.intent}</p>
        <p className="text-chalk leading-relaxed mb-4">{article.bodyMdx}</p>
        <div className="flex flex-wrap gap-2">
          {article.tags.map((tag) => (
            <span key={tag} className="text-[10px] font-telemetry border border-steel/30 px-2 py-1 uppercase text-steel">
              {tag}
            </span>
          ))}
        </div>
      </article>
      <div className="mt-4">
        <Link href="/insights" className="border border-steel/30 px-3 py-2 text-sm">
          Back to Insights
        </Link>
      </div>
    </PageShell>
  );
}
