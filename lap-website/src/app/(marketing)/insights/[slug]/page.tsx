import { notFound } from 'next/navigation';
import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { BreadcrumbJsonLd } from '@/components/seo/BreadcrumbJsonLd';
import { PageJsonLd } from '@/components/seo/PageJsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { insightEntries } from '@/data/insights-cms';
import { generateSeoMetadata } from '@/lib/seo';

export function generateStaticParams() {
  return insightEntries.map((entry) => ({ slug: entry.slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }) {
  const entry = insightEntries.find((e) => e.slug === params.slug);
  if (!entry) return generateSeoMetadata('/insights');
  return generateSeoMetadata('/insights', {
    title: entry.title,
    metaDescription: entry.summary.length >= 80
      ? entry.summary
      : `${entry.summary} Learn more about ${entry.tags.join(', ')} in motorsport telemetry analysis with LAP.`,
  });
}

export default function InsightDetailPage({ params }: { params: { slug: string } }) {
  const article = insightEntries.find((item) => item.slug === params.slug);
  if (!article) {
    notFound();
  }

  return (
    <>
    <BreadcrumbJsonLd pathname={`/insights/${article.slug}`} />
    <PageJsonLd
      type="Article"
      title={article.title}
      description={article.summary}
      pathname={`/insights/${article.slug}`}
    />
    <JsonLd
      pathname="/insights"
      article={{ title: article.title, datePublished: '2026-01-01', summary: article.summary }}
    />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro eyebrow="Insights" title={article.title} subtitle={article.summary} />
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
    </main>
    </>
  );
}
