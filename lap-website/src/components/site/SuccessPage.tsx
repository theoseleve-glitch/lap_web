import Link from 'next/link';

interface SuccessAction {
  label: string;
  href: string;
  primary?: boolean;
}

interface SuccessPageProps {
  title: string;
  summary: string;
  nextSteps: string[];
  actions: SuccessAction[];
  supportNote?: string;
}

export function SuccessPage({
  title,
  summary,
  nextSteps,
  actions,
  supportNote = 'Questions? Reach us at contact@lap-coach.racing',
}: SuccessPageProps) {
  const primary = actions.find((a) => a.primary) ?? actions[0];
  const secondary = actions.filter((a) => a !== primary);

  return (
    <section className="border border-steel/20 bg-concrete/30 p-6 md:p-8">
      <h2 className="font-monument text-[var(--text-h3)] mb-2">{title}</h2>
      <p className="text-steel mb-6">{summary}</p>

      {nextSteps.length > 0 && (
        <div className="mb-6">
          <p className="font-telemetry text-[10px] tracking-[0.12em] uppercase text-steel/60 mb-3">
            Next Steps
          </p>
          <ol className="space-y-2">
            {nextSteps.map((step, i) => (
              <li key={i} className="flex gap-3 text-sm text-chalk">
                <span className="font-telemetry text-steel shrink-0">{`0${i + 1}`}</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="flex flex-wrap gap-3 mb-4">
        {primary && (
          <Link
            href={primary.href}
            className="border border-pit-orange bg-pit-orange/10 px-5 py-2.5 text-sm text-chalk font-monument hover:bg-pit-orange/20 transition-colors"
          >
            {primary.label}
          </Link>
        )}
        {secondary.map((action) => (
          <Link
            key={action.href}
            href={action.href}
            className="border border-steel/30 px-4 py-2.5 text-sm text-steel hover:text-chalk hover:border-chalk transition-colors"
          >
            {action.label}
          </Link>
        ))}
      </div>

      <p className="text-steel/60 text-xs">{supportNote}</p>
    </section>
  );
}
