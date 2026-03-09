import Link from 'next/link';
import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/compare-tools');

const comparisonRows = [
  { feature: 'Upload to first insight', lap: 'Under 2 minutes', spreadsheet: '30–60 minutes' },
  { feature: 'Corner-by-corner coaching', lap: 'Automatic, with coaching hints', spreadsheet: 'Manual calculation per corner' },
  { feature: 'GPS track detection', lap: 'Automatic from coordinates', spreadsheet: 'Manual track matching' },
  { feature: 'Lap splitting', lap: 'Automatic from GPS', spreadsheet: 'Manual lap markers or timing' },
  { feature: 'Session-to-session comparison', lap: 'Built-in overlay charts', spreadsheet: 'Copy-paste between sheets' },
  { feature: 'Scoring (Pace, Consistency, etc.)', lap: 'Automated 5-dimension scoring /100', spreadsheet: 'Not available or custom formulas' },
  { feature: 'GG diagram', lap: 'Interactive with animation', spreadsheet: 'Static scatter plot' },
  { feature: 'Speed trace + hover sync', lap: 'Synced across map, speed, GG', spreadsheet: 'Not possible' },
  { feature: 'Multi-driver comparison', lap: 'Overlay by driver across sessions', spreadsheet: 'Manual chart setup per driver' },
  { feature: 'Data quality checks', lap: 'Automatic gap detection and interpolation', spreadsheet: 'Manual review for missing rows' },
  { feature: 'File size handling', lap: '10GB+ files, streaming pipeline', spreadsheet: 'Excel: ~1M rows max; crashes on large files' },
  { feature: 'Collaboration', lap: 'Shared workspace with team access', spreadsheet: 'Email or shared drive' },
];

export default function CompareToolsPage() {
  return (
    <>
      <JsonLd pathname="/compare-tools" />
      <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
        <PageIntro
          eyebrow="Why LAP"
          title="LAP vs Spreadsheet Analysis"
          subtitle="A side-by-side comparison of telemetry analysis in LAP versus manual spreadsheet workflows."
        />

        {/* Comparison table */}
        <section className="mb-10 overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-steel/20">
                <th className="text-left px-4 py-3 text-[10px] font-telemetry uppercase tracking-wider text-steel/60 w-1/3">Feature</th>
                <th className="text-left px-4 py-3 text-[10px] font-telemetry uppercase tracking-wider text-acid-green w-1/3">LAP Coach</th>
                <th className="text-left px-4 py-3 text-[10px] font-telemetry uppercase tracking-wider text-steel/60 w-1/3">Spreadsheet / DIY</th>
              </tr>
            </thead>
            <tbody>
              {comparisonRows.map((row) => (
                <tr key={row.feature} className="border-b border-steel/10 hover:bg-steel/5 transition-colors">
                  <td className="px-4 py-3 text-chalk font-medium">{row.feature}</td>
                  <td className="px-4 py-3 text-acid-green">{row.lap}</td>
                  <td className="px-4 py-3 text-steel">{row.spreadsheet}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* Key advantages */}
        <section className="mb-10">
          <h2 className="font-monument text-[var(--text-h2)] mb-4">Why Teams Switch from Spreadsheets</h2>
          <div className="grid md:grid-cols-3 gap-4">
            {[
              {
                title: 'Time Saved',
                value: '45 min → 2 min',
                description:
                  'From upload to actionable coaching insights. No formula building, no chart configuration, no manual lap splitting.',
              },
              {
                title: 'Consistency',
                description:
                  'Every session is analysed the same way. No risk of formula errors, broken references, or inconsistent methodology between analysts.',
                value: 'Standardised',
              },
              {
                title: 'Scale',
                description:
                  'Handle hundreds of sessions across a season. Spreadsheets break at scale; LAP was built for it from day one.',
                value: '10GB+ files',
              },
            ].map((item) => (
              <article key={item.title} className="border border-steel/20 bg-concrete/30 p-5">
                <p className="font-monument text-lg text-acid-green mb-1">{item.value}</p>
                <h3 className="font-monument text-sm text-chalk mb-2">{item.title}</h3>
                <p className="text-steel text-sm leading-relaxed">{item.description}</p>
              </article>
            ))}
          </div>
        </section>

        {/* When spreadsheets are fine */}
        <section className="border border-steel/20 p-5 mb-10">
          <h2 className="font-monument text-[var(--text-h3)] mb-3">When Spreadsheets Work</h2>
          <p className="text-sm text-steel leading-relaxed mb-3">
            Spreadsheets are fine for one-off analysis of a single session with simple lap time data.
            If you run fewer than 5 sessions per year and only need basic lap time tracking, a
            spreadsheet may be sufficient.
          </p>
          <p className="text-sm text-steel leading-relaxed">
            LAP becomes the better choice when you need corner-level coaching, multi-session trends,
            team collaboration, or when your data includes GPS coordinates and sensor channels.
          </p>
        </section>

        <div className="text-center">
          <Link
            href="/free-report/analyze"
            className="inline-block border border-pit-orange text-pit-orange px-6 py-3 text-sm font-telemetry uppercase tracking-wider hover:bg-pit-orange/10 transition-colors"
          >
            Try a Free Analysis
          </Link>
        </div>
      </main>
    </>
  );
}
