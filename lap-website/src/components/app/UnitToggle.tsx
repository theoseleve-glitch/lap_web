/**
 * UnitToggle.tsx — Compact unit system toggle for the app header/settings.
 *
 * Toggles between km/h ↔ mph, °C ↔ °F, metric ↔ imperial.
 */
'use client';

import { useUnitPreferences } from '@/lib/unit-preferences';

export function UnitToggle() {
  const { speed, temp, distance, setSpeed, setTemp, setDistance } = useUnitPreferences();

  return (
    <div className="flex items-center gap-3 text-xs font-body">
      <button
        type="button"
        onClick={() => setSpeed(speed === 'km/h' ? 'mph' : 'km/h')}
        className="px-2 py-0.5 rounded border border-steel/20 text-steel hover:text-chalk hover:border-steel/40 transition-colors"
        title="Toggle speed unit"
      >
        {speed}
      </button>
      <button
        type="button"
        onClick={() => setTemp(temp === 'C' ? 'F' : 'C')}
        className="px-2 py-0.5 rounded border border-steel/20 text-steel hover:text-chalk hover:border-steel/40 transition-colors"
        title="Toggle temperature unit"
      >
        °{temp}
      </button>
      <button
        type="button"
        onClick={() => setDistance(distance === 'metric' ? 'imperial' : 'metric')}
        className="px-2 py-0.5 rounded border border-steel/20 text-steel hover:text-chalk hover:border-steel/40 transition-colors"
        title="Toggle distance unit"
      >
        {distance === 'metric' ? 'm/km' : 'ft/mi'}
      </button>
    </div>
  );
}
