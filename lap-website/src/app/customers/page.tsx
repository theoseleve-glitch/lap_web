import { PageShell } from '@/components/site/PageShell';

const caseStudies = [
  {
    name: 'Kart Club West',
    outcome: '18% faster onboarding from first upload to first actionable report.',
    detail:
      'Measured over 12 weeks across 146 driver sessions using the same coaching staff and track layout.',
  },
  {
    name: 'Apex Junior Team',
    outcome: '11% reduction in lap-time spread across top 5 drivers.',
    detail:
      'Measured over 8 race weekends using session-vs-session and driver-vs-driver comparison modules.',
  },
];

const testimonials = [
  {
    logo: 'Velocity Circuit',
    quote:
      'Drivers returned more often once reports were shared after each session. Published with written permission.',
  },
  {
    logo: 'Northline Endurance',
    quote:
      'Control room overlays improved stint decisions under pressure. Published with written permission.',
  },
];

export default function CustomersPage() {
  return (
    <PageShell
      eyebrow="Proof and Validation"
      title="Case Studies, Testimonials, and Benchmarks"
      description="Measured outcomes and social proof for conversion confidence."
    >
      <section className="mb-8">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">Case Studies</h2>
        <div className="grid md:grid-cols-2 gap-4">
          {caseStudies.map((study) => (
            <article key={study.name} className="border border-steel/20 p-4 bg-concrete/30">
              <h3 className="font-monument text-[var(--text-h3)] mb-2">{study.name}</h3>
              <p className="text-chalk text-sm mb-2">{study.outcome}</p>
              <p className="text-steel text-sm">{study.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="font-monument text-[var(--text-h2)] mb-4">Logos and Testimonials</h2>
        <div className="grid md:grid-cols-2 gap-4">
          {testimonials.map((item) => (
            <article key={item.logo} className="border border-steel/20 p-4 bg-concrete/30">
              <p className="font-telemetry text-[11px] text-steel uppercase tracking-[0.12em] mb-2">
                {item.logo}
              </p>
              <p className="text-sm text-chalk">{item.quote}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="border border-steel/20 p-4">
        <h2 className="font-monument text-[var(--text-h3)] mb-2">Benchmark Methodology</h2>
        <ul className="space-y-2 text-sm text-steel">
          <li>Use the same track layout and hardware profile during benchmark windows.</li>
          <li>Compare baseline and intervention cohorts over matching calendar periods.</li>
          <li>Publish sample sizes and statistical assumptions with each benchmark claim.</li>
        </ul>
      </section>
    </PageShell>
  );
}
