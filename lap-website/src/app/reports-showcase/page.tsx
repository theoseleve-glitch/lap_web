import Link from 'next/link';
import { ShowcaseShell, ShowcaseSurface } from '@/components/showcase/ShowcaseShell';

const reportTypes = [
  {
    href: '/reports-showcase/normal',
    eyebrow: 'Normal Report',
    title: 'Session report',
    description:
      'Standard coaching report with score breakdown, session metadata, debrief, timeline, and lap-data surfaces.',
    chips: ['Overview', 'Timeline', 'Analytics', 'Lap Data'],
  },
  {
    href: '/reports-showcase/endurance',
    eyebrow: 'Endurance Report',
    title: 'Team / driver / stint report',
    description:
      'Endurance reporting stack with race report overview, driver comparison, selected driver details, and stint drill-down.',
    chips: ['Team Report', 'Driver Report', 'Stint Report'],
  },
];

export default function ReportsShowcaseIndexPage() {
  return (
    <ShowcaseShell
      eyebrow="Reports Showcase"
      title="Race report export hub"
      description="Entry point for the two actual report captures: the normal session report and the endurance race report."
      links={[
        { href: '/navigation-showcase', label: 'Navigation' },
        { href: '/strategy-showcase', label: 'Race Strategy' },
        { href: '/gamification-showcase', label: 'Gamification' },
      ]}
    >
      <ShowcaseSurface eyebrow="Select Report" title="Choose the report surface to capture">
        <div className="grid gap-5 lg:grid-cols-2">
          {reportTypes.map((report) => (
            <Link
              key={report.href}
              href={report.href}
              className="rounded-[26px] border border-white/10 bg-[linear-gradient(180deg,rgba(18,18,18,0.96),rgba(7,7,7,0.94))] p-6 transition-colors hover:border-acid-green/35"
            >
              <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-acid-green">
                {report.eyebrow}
              </p>
              <h2 className="mt-3 font-monument text-2xl text-chalk">{report.title}</h2>
              <p className="mt-3 max-w-xl font-body text-sm leading-6 text-steel">
                {report.description}
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {report.chips.map((chip) => (
                  <span
                    key={chip}
                    className="rounded-full border border-white/10 px-3 py-1 font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel"
                  >
                    {chip}
                  </span>
                ))}
              </div>
              <div className="mt-6 font-telemetry text-[11px] uppercase tracking-[0.16em] text-chalk">
                Open report
              </div>
            </Link>
          ))}
        </div>
      </ShowcaseSurface>
    </ShowcaseShell>
  );
}
