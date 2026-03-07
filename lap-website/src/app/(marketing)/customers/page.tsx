import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/customers');

const caseStudies = [
  {
    category: 'Kart Racing Academy',
    metric: '18% faster onboarding',
    description:
      'A kart club running junior development programmes used LAP to standardise post-session debriefs. Drivers received automated coaching cards within minutes of each session, replacing ad-hoc verbal feedback.',
    methodology:
      'Measured over 12 weeks across 146 driver sessions. Baseline period (6 weeks) compared to intervention period (6 weeks) using the same coaching staff, track layout, and kart specification.',
    highlight: 'Time from first upload to first actionable coaching report dropped from 45 minutes to under 8.',
  },
  {
    category: 'Junior Single-Seater Team',
    metric: '11% reduction in lap-time spread',
    description:
      'A 5-driver junior team used session-vs-session and driver-vs-driver comparison modules to identify consistency gaps. Coaches focused debrief time on the two corners with highest avg_time_loss_ms.',
    methodology:
      'Measured over 8 race weekends. Spread calculated as coefficient of variation (CV%) across each driver\'s qualifying laps. Baseline CV% averaged 2.8%; post-intervention averaged 2.5%.',
    highlight: 'Top 5 drivers converged within 0.3s of each other by the final weekend, down from 0.7s initially.',
  },
  {
    category: 'Endurance Racing Operation',
    metric: '2 fewer unplanned pit stops per 6-hour race',
    description:
      'A 4-car endurance team integrated the Race Strategy Dashboard for live stint monitoring. Tyre degradation detection flagged pace fade before drivers reported it, enabling proactive pit calls.',
    methodology:
      'Measured across 4 endurance races (6-hour format). Compared to the team\'s previous season data with manual timing and radio-based strategy calls.',
    highlight: 'Pit window accuracy improved from ±3 laps to ±1 lap, reducing time lost to late stops.',
  },
];

const testimonials = [
  {
    role: 'Head Coach, Regional Kart Championship',
    quote:
      'Drivers returned more often once reports were shared after each session. The scoring system gave them a target to beat — not just a lap time, but a breakdown of where the time was.',
  },
  {
    role: 'Race Engineer, GT Endurance Team',
    quote:
      'Control room overlays improved stint decisions under pressure. Having degradation trends and pit windows on one screen meant fewer radio calls and faster reactions.',
  },
  {
    role: 'Team Principal, Junior Formula Academy',
    quote:
      'The Corner Coaching table is where the real value is. Instead of arguing about feel, we pointed to the data and focused on one corner per session. Progress was measurable.',
  },
];

export default function CustomersPage() {
  return (
    <>
    <JsonLd pathname="/customers" />
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Results"
        title="Measured Outcomes from Real Teams"
        subtitle="Anonymous case studies and testimonials from teams using LAP in competition."
      />
      {/* Case Studies */}
      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">Case Studies</h2>
        <div className="space-y-6">
          {caseStudies.map((study) => (
            <article key={study.category} className="border border-steel/20 p-5 bg-concrete/30">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div>
                  <p className="font-telemetry text-[10px] uppercase tracking-[0.12em] text-steel mb-1">
                    {study.category}
                  </p>
                  <h3 className="font-monument text-[var(--text-h3)] text-acid-green">
                    {study.metric}
                  </h3>
                </div>
              </div>
              <p className="text-chalk text-sm leading-relaxed mb-3">{study.description}</p>
              <p className="text-steel text-sm leading-relaxed mb-3">
                <span className="text-chalk font-telemetry text-[10px] uppercase tracking-wider">
                  Methodology:
                </span>{' '}
                {study.methodology}
              </p>
              <p className="text-pit-orange text-sm">{study.highlight}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Testimonials */}
      <section className="mb-10">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">What Teams Say</h2>
        <div className="grid md:grid-cols-3 gap-4">
          {testimonials.map((item) => (
            <article key={item.role} className="border border-steel/20 p-5 bg-concrete/30">
              <blockquote className="text-sm text-chalk leading-relaxed mb-3">
                &ldquo;{item.quote}&rdquo;
              </blockquote>
              <p className="font-telemetry text-[10px] text-steel uppercase tracking-[0.12em]">
                {item.role}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* Methodology */}
      <section className="border border-steel/20 p-5">
        <h2 className="font-monument text-[var(--text-h3)] mb-3">Benchmark Methodology</h2>
        <div className="text-sm text-steel leading-relaxed space-y-2">
          <p>All case studies follow these measurement standards:</p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>Same track layout and hardware profile during baseline and intervention periods</li>
            <li>Baseline and intervention cohorts compared over matching calendar periods</li>
            <li>Sample sizes and statistical assumptions published with each claim</li>
            <li>Lap-time spread measured as coefficient of variation (CV%) to normalise across tracks</li>
          </ul>
          <p>
            Customer names are anonymised. Outcomes may vary based on team size, driver experience,
            and track conditions.
          </p>
        </div>
      </section>

      <div className="mt-8 text-center">
        <Link
          href="/demo"
          className="inline-block border border-pit-orange text-pit-orange px-4 py-2 text-sm font-telemetry uppercase tracking-wider hover:bg-pit-orange/10 transition-colors"
        >
          See It In Action
        </Link>
      </div>
    </main>
    </>
  );
}
