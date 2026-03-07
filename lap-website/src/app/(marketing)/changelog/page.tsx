import { PageIntro } from '@/components/ui/PageIntro';
import { changelog } from '@/data/changelog';

const TAG_STYLES: Record<string, string> = {
  feature: 'border-acid-green/40 text-acid-green',
  fix: 'border-marshal-yellow/40 text-marshal-yellow',
  improvement: 'border-racing-purple/40 text-racing-purple',
  security: 'border-pit-orange/40 text-pit-orange',
  breaking: 'border-safety-red/40 text-safety-red',
};

export const metadata = {
  title: 'Changelog | LAP',
  description: 'Product updates, new features, and improvements to LAP telemetry analysis.',
};

export default function ChangelogPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-10 md:py-14">
      <PageIntro
        eyebrow="Changelog"
        title="What's New"
        subtitle="Product updates, new features, and improvements."
      />
      <ol className="space-y-6">
        {changelog.map((entry) => (
          <li key={entry.version} className="border border-steel/20 bg-concrete/30 p-5 md:p-6">
            <div className="flex flex-wrap items-baseline gap-3 mb-2">
              <span className="font-monument text-[var(--text-h3)]">{entry.version}</span>
              <time className="font-telemetry text-[11px] tracking-[0.12em] uppercase text-steel">
                {entry.date}
              </time>
              <div className="flex gap-1.5">
                {entry.tags.map((tag) => (
                  <span
                    key={tag}
                    className={`border px-2 py-0.5 text-[10px] font-telemetry uppercase tracking-wider ${TAG_STYLES[tag] ?? 'border-steel/30 text-steel'}`}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
            <p className="text-chalk mb-3">{entry.summary}</p>
            {entry.details && entry.details.length > 0 && (
              <ul className="space-y-1">
                {entry.details.map((detail, i) => (
                  <li key={i} className="text-sm text-steel flex gap-2">
                    <span className="text-steel/40 shrink-0">&mdash;</span>
                    {detail}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </main>
  );
}
