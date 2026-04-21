import type { PanelContext } from '@/lib/panel-registry';

export function OptimizerPanel({ optimizer }: PanelContext) {
  if (!optimizer) {
    return (
      <section className="rounded-xl bg-concrete border border-steel/10 p-6">
        <h2 className="font-monument text-chalk text-base">Optimizer</h2>
        <p className="text-steel text-sm font-body mt-2">Optimizer not available for this session.</p>
      </section>
    );
  }

  const isFullFidelity = optimizer.depth === 'full_fidelity';
  const depthLabel = isFullFidelity ? 'Full fidelity' : 'Trajectory-only';

  return (
    <section className="rounded-xl bg-concrete border border-steel/10 p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="font-monument text-chalk text-base">Optimizer</h2>
        <span className="text-[10px] font-telemetry text-steel uppercase tracking-wider">
          {depthLabel}
        </span>
      </header>

      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-steel text-xs font-telemetry uppercase tracking-wider">Theoretical lap</dt>
          <dd className="text-chalk font-telemetry text-lg">{optimizer.theoretical_lap_time_s.toFixed(2)}s</dd>
        </div>
        {typeof optimizer.total_time_loss_s === 'number' && (
          <div>
            <dt className="text-steel text-xs font-telemetry uppercase tracking-wider">Time loss</dt>
            <dd className="text-acid-green font-telemetry text-lg">+{optimizer.total_time_loss_s.toFixed(2)}s</dd>
          </div>
        )}
      </dl>

      {isFullFidelity && optimizer.reconstructed_inputs && (
        <div data-testid="reconstructed-inputs-summary" className="border-t border-steel/10 pt-4">
          <h3 className="text-xs font-telemetry text-steel uppercase tracking-wider mb-2">Reconstructed inputs</h3>
          <p className="text-chalk text-sm font-body">
            {optimizer.reconstructed_inputs.distance_m.length} samples of throttle, brake, and steering
            traces for delta attribution.
          </p>
        </div>
      )}

      {optimizer.corner_deltas && optimizer.corner_deltas.length > 0 && (
        <div className="border-t border-steel/10 pt-4">
          <h3 className="text-xs font-telemetry text-steel uppercase tracking-wider mb-2">Corner deltas</h3>
          <ul className="space-y-1.5">
            {optimizer.corner_deltas.map((d) => (
              <li key={`${d.corner_id}-${d.phase ?? ''}`} className="flex items-baseline gap-2 text-sm">
                <span className="text-chalk font-body flex-1">{d.corner_id} — {d.root_cause}</span>
                <span className="text-acid-green font-telemetry text-xs">+{d.time_loss_s.toFixed(2)}s</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
