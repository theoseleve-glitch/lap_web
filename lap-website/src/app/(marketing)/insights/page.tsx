'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { insightEntries, insightTags } from '@/data/insights-cms';

export default function InsightsPage() {
  const [query, setQuery] = useState('');
  const [activeTag, setActiveTag] = useState('all');

  const filtered = useMemo(() => {
    return insightEntries.filter((entry) => {
      const matchesTag = activeTag === 'all' || entry.tags.includes(activeTag);
      const q = query.trim().toLowerCase();
      const matchesQuery =
        q.length === 0 ||
        entry.title.toLowerCase().includes(q) ||
        entry.intent.toLowerCase().includes(q) ||
        entry.summary.toLowerCase().includes(q);
      return matchesTag && matchesQuery;
    });
  }, [activeTag, query]);

  return (
    <>
    <JsonLd pathname="/insights" />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Learn"
        title="Telemetry Insights"
        subtitle="Practical motorsport analysis articles covering corners, consistency, strategy, and coaching."
      />
      <section className="mb-6 grid md:grid-cols-[2fr_3fr] gap-3">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search intent, title, or summary"
          className="bg-concrete border border-steel/30 px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap gap-2">
          <button
            className={`px-3 py-2 border text-xs font-telemetry tracking-[0.12em] uppercase ${
              activeTag === 'all' ? 'border-pit-orange text-chalk' : 'border-steel/30 text-steel'
            }`}
            onClick={() => setActiveTag('all')}
          >
            All
          </button>
          {insightTags.map((tag) => (
            <button
              key={tag}
              className={`px-3 py-2 border text-xs font-telemetry tracking-[0.12em] uppercase ${
                activeTag === tag ? 'border-pit-orange text-chalk' : 'border-steel/30 text-steel'
              }`}
              onClick={() => setActiveTag(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        {filtered.map((article) => (
          <article key={article.slug} className="border border-steel/20 p-4 bg-concrete/30">
            <h2 className="font-monument text-[var(--text-h3)] mb-2">{article.title}</h2>
            <p className="text-steel text-sm mb-3">{article.summary}</p>
            <div className="flex flex-wrap gap-2 mb-3">
              {article.tags.map((tag) => (
                <span key={tag} className="text-[10px] font-telemetry border border-steel/30 px-2 py-1 uppercase text-steel">
                  {tag}
                </span>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              <Link href={`/insights/${article.slug}`} className="text-sm border border-steel/30 px-3 py-1">
                Open Insight
              </Link>
              <Link href={article.relatedHref} className="text-sm border border-steel/30 px-3 py-1">
                Explore Related Product Module
              </Link>
            </div>
          </article>
        ))}
      </section>
    </main>
    </>
  );
}
