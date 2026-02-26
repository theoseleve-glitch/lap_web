import Link from 'next/link';
import type { PersonaPage as PersonaPageData } from '@/data/personas';
import { PageShell } from '@/components/site/PageShell';
import { StructuredData } from '@/components/site/StructuredData';

interface PersonaPageProps {
  persona: PersonaPageData;
}

export function PersonaPage({ persona }: PersonaPageProps) {
  return (
    <>
      <StructuredData
        data={{
          '@context': 'https://schema.org',
          '@type': 'WebPage',
          name: persona.title,
          description: persona.summary,
          url: `https://lap.racing/${persona.slug}`,
        }}
      />
      <PageShell eyebrow="Persona Landing" title={persona.title} description={persona.summary}>
        <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
          <article className="border border-steel/20 p-5 bg-concrete/40">
            <p className="font-monument text-[var(--text-h3)] mb-4">{persona.subtitle}</p>
            <ul className="space-y-3 text-steel">
              {persona.bullets.map((bullet) => (
                <li key={bullet} className="border border-steel/20 p-3 bg-asphalt/30">
                  {bullet}
                </li>
              ))}
            </ul>
          </article>
          <aside className="border border-steel/20 p-5 bg-concrete/20">
            <h2 className="font-monument text-[var(--text-h3)] mb-3">Action</h2>
            <div className="flex flex-col gap-3">
              <Link href={persona.primaryCta.href} className="border border-pit-orange px-4 py-2 text-sm">
                {persona.primaryCta.label}
              </Link>
              <Link href={persona.secondaryCta.href} className="border border-steel/30 px-4 py-2 text-sm">
                {persona.secondaryCta.label}
              </Link>
            </div>
          </aside>
        </section>
      </PageShell>
    </>
  );
}
