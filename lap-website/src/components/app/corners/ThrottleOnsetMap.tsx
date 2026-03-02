'use client';

export function ThrottleOnsetMap() {
  return (
    <div className="bg-concrete rounded-lg border border-steel/10 p-4">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-sm text-chalk font-telemetry">Throttle Onset</h3>
        <span className="text-[9px] px-2 py-0.5 rounded bg-steel/10 text-steel/40 font-telemetry">
          Coming Soon
        </span>
      </div>
      <div className="rounded border border-dashed border-steel/20 p-6 flex items-center justify-center min-h-[120px]">
        <p className="text-xs text-steel/40 font-body text-center">
          Throttle application point per corner
        </p>
      </div>
    </div>
  );
}
