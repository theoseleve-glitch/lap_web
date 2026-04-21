import type { PanelContext } from '@/lib/panel-registry';

const INPUT_TAGS = ['throttle', 'brake', 'steer'] as const;

export function CoachingPanel({ session, coaching }: PanelContext) {
  if (!coaching) {
    return (
      <section className="rounded-xl bg-concrete border border-steel/10 p-6">
        <header className="flex items-center justify-between mb-3">
          <h2 className="font-monument text-chalk text-base">Coaching</h2>
        </header>
        <p className="text-steel text-sm font-body">Coaching not available for this session.</p>
      </section>
    );
  }

  const channels = new Set(session.capabilities.channels ?? []);
  const hasInputs = INPUT_TAGS.every((t) => channels.has(t));

  return (
    <section className="rounded-xl bg-concrete border border-steel/10 p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="font-monument text-chalk text-base">Coaching</h2>
        {!hasInputs && (
          <span className="text-[10px] font-telemetry text-steel uppercase tracking-wider">
            Output-based
          </span>
        )}
      </header>

      {!hasInputs && (
        <p className="text-xs font-body text-steel/80">
          Deeper input-aware coaching (throttle, brake, steering patterns) requires simracing
          telemetry or an optional input bolt-on.
        </p>
      )}

      {coaching.storyline.length > 0 && (
        <ul className="space-y-2">
          {coaching.storyline.map((s) => (
            <li key={s.weakness_key} className="text-sm">
              <p className="text-chalk font-body">{s.headline}</p>
              {s.detail && <p className="text-steel text-xs font-body mt-0.5">{s.detail}</p>}
            </li>
          ))}
        </ul>
      )}

      {coaching.global_focus.length > 0 && (
        <div className="border-t border-steel/10 pt-4">
          <h3 className="text-xs font-telemetry text-steel uppercase tracking-wider mb-2">Focus</h3>
          <ol className="space-y-1.5">
            {coaching.global_focus.map((f) => (
              <li key={f.weakness_key} className="flex items-start gap-2 text-sm">
                <span className="text-steel/60 font-telemetry text-xs w-4">#{f.rank}</span>
                <span className="text-chalk font-body flex-1">{f.title}</span>
                {typeof f.cost_ms === 'number' && (
                  <span className="text-acid-green font-telemetry text-xs">+{(f.cost_ms / 1000).toFixed(2)}s</span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
