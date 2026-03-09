'use client';

/**
 * LogoWall — Displays logos of teams/organizations using LAP.
 * Uses placeholder text logos until real brand assets are available.
 */

const LOGOS = [
  { name: 'Karting Academy UK', abbr: 'KA' },
  { name: 'Alpine GT Racing', abbr: 'AGR' },
  { name: 'Nordic Kart Series', abbr: 'NKS' },
  { name: 'Endurance Pro Racing', abbr: 'EPR' },
  { name: 'Circuit de Catalunya', abbr: 'CC' },
  { name: 'Junior Formula Europe', abbr: 'JFE' },
  { name: 'Pacific Motorsport', abbr: 'PM' },
  { name: 'Touring Car Alliance', abbr: 'TCA' },
];

export function LogoWall() {
  return (
    <section className="py-10 md:py-14 border-t border-steel/10" aria-label="Trusted by teams">
      <div className="grid-lap">
        <div className="col-span-full text-center mb-6">
          <p className="font-telemetry text-[11px] tracking-[0.16em] uppercase text-steel/60">
            Trusted by teams &amp; academies
          </p>
        </div>
        <div className="col-span-full">
          <div className="flex flex-wrap items-center justify-center gap-8 md:gap-12 opacity-50">
            {LOGOS.map((logo) => (
              <div
                key={logo.name}
                className="flex items-center gap-2 text-steel/60 hover:text-steel transition-colors"
                title={logo.name}
              >
                <span className="font-monument text-lg tracking-wider">{logo.abbr}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
