import Link from 'next/link';
import { personaPages } from '@/data/personas';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export function S5Personas() {
  return (
    <section
      id="s5-personas"
      data-accent="orange"
      className="room relative py-16 md:py-24 border-t border-steel/20"
      aria-label="Persona pages"
    >
      <div className="grid-lap">
        <div className="col-span-full mb-8">
          <h2 className="font-monument text-[clamp(42px,7vw,76px)] leading-[0.9]">
            PERSONA
            <br />
            LANDING PAGES
          </h2>
          <ReversibleCard
            title="Persona-Specific Journeys"
            description="Drivers, circuits, teams, and endurance programs each get dedicated messaging, proof, and conversion paths aligned to their buying intent."
            className="max-w-2xl mt-4"
          />
        </div>

        <div className="col-span-full grid grid-cols-1 md:grid-cols-2 gap-4">
          {personaPages.map((persona) => (
            <article key={persona.slug} className="border border-steel/20 bg-concrete/40 p-5">
              <h3 className="font-monument text-[var(--text-h3)] mb-2">{persona.title}</h3>
              <p className="text-sm text-steel mb-3">{persona.subtitle}</p>
              <div className="flex flex-wrap gap-2">
                <Link
                  href={`/${persona.slug}`}
                  className="border border-chalk/50 px-3 py-1 text-xs font-telemetry tracking-[0.12em]"
                >
                  OPEN PAGE
                </Link>
                <Link
                  href={persona.primaryCta.href}
                  className="border border-pit-orange px-3 py-1 text-xs font-telemetry tracking-[0.12em]"
                >
                  {persona.primaryCta.label.toUpperCase()}
                </Link>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
