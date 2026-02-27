import Link from 'next/link';
import type { PersonaPage as PersonaPageData } from '@/data/personas';
import { PageShell } from '@/components/site/PageShell';
import { StructuredData } from '@/components/site/StructuredData';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

interface PersonaPageProps {
  persona: PersonaPageData;
}

export function PersonaPage({ persona }: PersonaPageProps) {
  const heroImageBySlug: Record<PersonaPageData['slug'], string> = {
    drivers: '/images/screenshots/corner-replay.png',
    circuits: '/images/screenshots/dashboard-hero.png',
    teams: '/images/screenshots/score-overview.png',
    endurance: '/images/screenshots/driving-style-radar.png',
  };

  return (
    <>
      <StructuredData
        data={{
          '@context': 'https://schema.org',
          '@type': 'WebPage',
          name: persona.title,
          description: persona.summary,
          url: `https://www.lap-coach.racing/${persona.slug}`,
        }}
      />
      <PageShell eyebrow={persona.title} title={persona.subtitle} description={persona.summary}>
        <section className="grid lg:grid-cols-[2fr_1fr] gap-6">
          <article className="border border-steel/20 p-5 bg-concrete/40">
            <img
              src={heroImageBySlug[persona.slug]}
              alt={`${persona.title} workflow`}
              className="w-full h-56 object-cover border border-steel/20 mb-4"
            />
            <ul className="space-y-3 text-steel">
              {persona.bullets.map((bullet, index) => (
                <li key={bullet}>
                  <ReversibleCard title={`Outcome ${index + 1}`} description={bullet} />
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
