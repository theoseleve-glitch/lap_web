import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import { PageShell } from '@/components/site/PageShell';
import { insightEntries } from '@/data/insights-cms';

export function generateStaticParams() {
  return insightEntries.map((entry) => ({ slug: entry.slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const article = insightEntries.find((item) => item.slug === params.slug);
  if (!article) return { title: 'Insight Not Found | LAP' };
  return {
    title: `${article.title} | LAP`,
    description: article.summary,
  };
}

export default function InsightDetailPage({ params }: { params: { slug: string } }) {
  const article = insightEntries.find((item) => item.slug === params.slug);
  if (!article) {
    notFound();
  }

  return (
    <PageShell eyebrow="Insights" title={article.title} description={article.summary}>
      <article className="border border-steel/20 bg-concrete/30 p-6">
        <div className="text-chalk leading-relaxed space-y-4 mb-6">
          {article.bodyMdx.split('. ').reduce<string[]>((acc, sentence, i, arr) => {
            // Group sentences into paragraphs of ~2-3 sentences each
            const last = acc.length > 0 ? acc[acc.length - 1] : '';
            const withDot = i < arr.length - 1 ? sentence + '.' : sentence;
            if (last.length > 0 && last.split('. ').length < 3) {
              acc[acc.length - 1] = last + ' ' + withDot;
            } else {
              acc.push(withDot);
            }
            return acc;
          }, []).map((paragraph, i) => (
            <p key={i}>{paragraph}</p>
          ))}
        </div>

        <div className="flex flex-wrap gap-2 mb-4">
          {article.tags.map((tag) => (
            <span
              key={tag}
              className="text-[10px] font-telemetry border border-steel/30 px-2 py-1 uppercase text-steel"
            >
              {tag}
            </span>
          ))}
        </div>

        {article.relatedHref && (
          <Link
            href={article.relatedHref}
            className="inline-block text-sm text-pit-orange border border-pit-orange/40 px-3 py-1.5 hover:bg-pit-orange/10 transition-colors"
          >
            Explore Related Feature
          </Link>
        )}
      </article>
      <div className="mt-4">
        <Link href="/insights" className="border border-steel/30 px-3 py-2 text-sm text-steel hover:text-chalk transition-colors">
          &larr; Back to Insights
        </Link>
      </div>
    </PageShell>
  );
}
