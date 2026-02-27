'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader } from '@/components/app';

interface DriverForm {
  driver_name: string;
  weight_kg: string;
  com_channel: string;
  color_hex: string;
  min_stint_s: string;
  max_stint_s: string;
  min_cumulative_s: string;
  max_cumulative_s: string;
  min_rest_s: string;
  showConstraints: boolean;
}

interface WindowForm {
  window_type: string;
  label: string;
  start_mm: string;
  start_ss: string;
  end_mm: string;
  end_ss: string;
  refuel_allowed: boolean;
  driver_change_allowed: boolean;
}

const DEFAULT_DRIVER: DriverForm = {
  driver_name: '',
  weight_kg: '',
  com_channel: '',
  color_hex: '#3B82F6',
  min_stint_s: '',
  max_stint_s: '',
  min_cumulative_s: '',
  max_cumulative_s: '',
  min_rest_s: '',
  showConstraints: false,
};

const DEFAULT_WINDOW: WindowForm = {
  window_type: 'pitlane',
  label: '',
  start_mm: '0',
  start_ss: '0',
  end_mm: '0',
  end_ss: '0',
  refuel_allowed: true,
  driver_change_allowed: true,
};

const DRIVER_COLORS = ['#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4', '#F97316'];

function mmssToSeconds(mm: string, ss: string): number {
  return (parseInt(mm) || 0) * 60 + (parseInt(ss) || 0);
}

function parseNum(v: string): number | null {
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

// Input styling
const inputCls = 'w-full bg-asphalt border border-steel/30 px-3 py-2 text-chalk font-body text-sm focus:border-pit-orange focus:outline-none';
const labelCls = 'block text-steel font-telemetry text-[11px] tracking-[0.08em] uppercase mb-1';
const sectionCls = 'bg-concrete border border-steel/20 p-5 mb-4';

export default function NewRacePage() {
  const router = useRouter();
  const [error, setError] = useState('');

  // Form state
  const [raceName, setRaceName] = useState('');
  const [teamName, setTeamName] = useState('');
  const [trackName, setTrackName] = useState('');
  const [durationH, setDurationH] = useState('3');
  const [durationM, setDurationM] = useState('0');
  const [desiredStints, setDesiredStints] = useState('4');

  // Drivers
  const [drivers, setDrivers] = useState<DriverForm[]>([
    { ...DEFAULT_DRIVER, color_hex: DRIVER_COLORS[0] },
    { ...DEFAULT_DRIVER, color_hex: DRIVER_COLORS[1] },
  ]);

  // Pit Strategy
  const [minPitStop, setMinPitStop] = useState('60');
  const [pitSpeed, setPitSpeed] = useState('');
  const [quickPitStop, setQuickPitStop] = useState('');
  const [mandatoryChange, setMandatoryChange] = useState(true);
  const [refuelingAllowed, setRefuelingAllowed] = useState(true);

  // Pit Windows
  const [windows, setWindows] = useState<WindowForm[]>([]);

  // Fuel & Weight
  const [fuelAutonomyM, setFuelAutonomyM] = useState('');
  const [fuelAutonomyS, setFuelAutonomyS] = useState('');
  const [emptyKart, setEmptyKart] = useState('');
  const [fullTank, setFullTank] = useState('');
  const [minTotal, setMinTotal] = useState('');
  const [referenceWeight, setReferenceWeight] = useState('');
  const [weighOnExit, setWeighOnExit] = useState(false);

  // Qualifying
  const [showQuali, setShowQuali] = useState(false);
  const [qualiDuration, setQualiDuration] = useState('');
  const [refuelAfterQuali, setRefuelAfterQuali] = useState(false);

  const mutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<{ race_id: number }>('/race-strategy/', payload),
    onSuccess: (data) => {
      router.push(`/app/race-strategy/${data.race_id}`);
    },
    onError: (err: Error) => {
      setError(err.message);
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    const raceDurationS = (parseInt(durationH) || 0) * 3600 + (parseInt(durationM) || 0) * 60;
    if (!raceName.trim()) { setError('Race name is required'); return; }
    if (raceDurationS <= 0) { setError('Race duration must be positive'); return; }
    if (drivers.filter(d => d.driver_name.trim()).length < 1) { setError('At least one driver is required'); return; }

    const payload = {
      race: {
        race_name: raceName.trim(),
        team_name: teamName.trim() || null,
        track_name: trackName.trim() || null,
        race_duration_s: raceDurationS,
        desired_stints: parseInt(desiredStints) || 4,
        min_pit_stop_s: parseInt(minPitStop) || 60,
        pit_speed_kmh: parseNum(pitSpeed),
        quick_pit_stop_s: parseNum(quickPitStop),
        mandatory_driver_change: mandatoryChange ? 1 : 0,
        refueling_allowed: refuelingAllowed ? 1 : 0,
        fuel_autonomy_s: mmssToSeconds(fuelAutonomyM, fuelAutonomyS) || null,
        empty_kart_kg: parseNum(emptyKart),
        full_tank_kg: parseNum(fullTank),
        min_total_kart_kg: parseNum(minTotal),
        reference_weight_kg: parseNum(referenceWeight),
        weigh_on_pit_exit: weighOnExit ? 1 : 0,
        qualifying_duration_s: parseNum(qualiDuration),
        refuel_after_quali: refuelAfterQuali ? 1 : 0,
      },
      drivers: drivers
        .filter(d => d.driver_name.trim())
        .map((d, i) => ({
          driver_name: d.driver_name.trim(),
          driver_order: i + 1,
          weight_kg: parseNum(d.weight_kg),
          com_channel: d.com_channel.trim() || null,
          color_hex: d.color_hex,
          min_stint_s: parseNum(d.min_stint_s),
          max_stint_s: parseNum(d.max_stint_s),
          min_cumulative_s: parseNum(d.min_cumulative_s),
          max_cumulative_s: parseNum(d.max_cumulative_s),
          min_rest_s: parseNum(d.min_rest_s) ?? 0,
        })),
      windows: windows.map((w, i) => ({
        window_type: w.window_type,
        label: w.label.trim() || null,
        start_s: mmssToSeconds(w.start_mm, w.start_ss),
        end_s: mmssToSeconds(w.end_mm, w.end_ss),
        refuel_allowed: w.refuel_allowed ? 1 : 0,
        driver_change_allowed: w.driver_change_allowed ? 1 : 0,
        window_order: i + 1,
      })),
    };

    mutation.mutate(payload);
  }

  function addDriver() {
    setDrivers(prev => [...prev, { ...DEFAULT_DRIVER, color_hex: DRIVER_COLORS[prev.length % DRIVER_COLORS.length] }]);
  }

  function removeDriver(idx: number) {
    setDrivers(prev => prev.filter((_, i) => i !== idx));
  }

  function updateDriver(idx: number, field: keyof DriverForm, value: string | boolean) {
    setDrivers(prev => prev.map((d, i) => i === idx ? { ...d, [field]: value } : d));
  }

  function addWindow() {
    setWindows(prev => [...prev, { ...DEFAULT_WINDOW }]);
  }

  function removeWindow(idx: number) {
    setWindows(prev => prev.filter((_, i) => i !== idx));
  }

  function updateWindow(idx: number, field: keyof WindowForm, value: string | boolean) {
    setWindows(prev => prev.map((w, i) => i === idx ? { ...w, [field]: value } : w));
  }

  return (
    <div className="max-w-4xl">
      <PageHeader title="New Race" subtitle="Configure your endurance race strategy" />

      {error && (
        <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 text-safety-red font-body text-sm">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        {/* Race Details */}
        <div className={sectionCls}>
          <h2 className="font-monument text-lg text-chalk mb-4">Race Details</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Race Name *</label>
              <input className={inputCls} value={raceName} onChange={e => setRaceName(e.target.value)} placeholder="24h Le Mans Kart" />
            </div>
            <div>
              <label className={labelCls}>Team Name</label>
              <input className={inputCls} value={teamName} onChange={e => setTeamName(e.target.value)} placeholder="Apex Racing" />
            </div>
            <div>
              <label className={labelCls}>Track</label>
              <input className={inputCls} value={trackName} onChange={e => setTrackName(e.target.value)} placeholder="Circuit de Pau-Arnos" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className={labelCls}>Duration (h)</label>
                <input type="number" className={inputCls} value={durationH} onChange={e => setDurationH(e.target.value)} min="0" />
              </div>
              <div>
                <label className={labelCls}>Minutes</label>
                <input type="number" className={inputCls} value={durationM} onChange={e => setDurationM(e.target.value)} min="0" max="59" />
              </div>
              <div>
                <label className={labelCls}>Stints</label>
                <input type="number" className={inputCls} value={desiredStints} onChange={e => setDesiredStints(e.target.value)} min="1" />
              </div>
            </div>
          </div>
        </div>

        {/* Drivers */}
        <div className={sectionCls}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-monument text-lg text-chalk">Drivers</h2>
            <button type="button" onClick={addDriver} className="px-3 py-1 text-sm font-telemetry text-pit-orange border border-pit-orange/40 hover:bg-pit-orange/10 transition-colors">
              + Add Driver
            </button>
          </div>
          <p className="text-steel font-body text-sm mb-3">Enter at least one driver name to build the strategy.</p>
          <div className="space-y-3">
            {drivers.map((d, i) => (
              <div key={i} className="bg-asphalt/40 border border-steel/10 p-3">
                <div className="flex items-center gap-3 mb-2">
                  <input type="color" value={d.color_hex} onChange={e => updateDriver(i, 'color_hex', e.target.value)} className="w-8 h-8 rounded cursor-pointer bg-transparent border-0" />
                  <input aria-label="Driver name" className={`${inputCls} flex-1 min-w-[12rem]`} value={d.driver_name} onChange={e => updateDriver(i, 'driver_name', e.target.value)} placeholder="Driver name" />
                  <input className={`${inputCls} w-24`} value={d.weight_kg} onChange={e => updateDriver(i, 'weight_kg', e.target.value)} placeholder="kg" type="number" step="0.1" />
                  <input className={`${inputCls} w-24`} value={d.com_channel} onChange={e => updateDriver(i, 'com_channel', e.target.value)} placeholder="COM" />
                  <button type="button" onClick={() => updateDriver(i, 'showConstraints', !d.showConstraints)} className="text-steel hover:text-chalk text-xs font-telemetry">
                    {d.showConstraints ? '▼' : '▶'} Rules
                  </button>
                  {drivers.length > 1 && (
                    <button type="button" onClick={() => removeDriver(i)} className="text-safety-red hover:text-safety-red/80 text-sm">✕</button>
                  )}
                </div>
                {d.showConstraints && (
                  <div className="grid grid-cols-5 gap-2 mt-2 pl-11">
                    <div><label className={labelCls}>Min stint(s)</label><input className={inputCls} value={d.min_stint_s} onChange={e => updateDriver(i, 'min_stint_s', e.target.value)} type="number" /></div>
                    <div><label className={labelCls}>Max stint(s)</label><input className={inputCls} value={d.max_stint_s} onChange={e => updateDriver(i, 'max_stint_s', e.target.value)} type="number" /></div>
                    <div><label className={labelCls}>Min total(s)</label><input className={inputCls} value={d.min_cumulative_s} onChange={e => updateDriver(i, 'min_cumulative_s', e.target.value)} type="number" /></div>
                    <div><label className={labelCls}>Max total(s)</label><input className={inputCls} value={d.max_cumulative_s} onChange={e => updateDriver(i, 'max_cumulative_s', e.target.value)} type="number" /></div>
                    <div><label className={labelCls}>Min rest(s)</label><input className={inputCls} value={d.min_rest_s} onChange={e => updateDriver(i, 'min_rest_s', e.target.value)} type="number" /></div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Pit Strategy */}
        <div className={sectionCls}>
          <h2 className="font-monument text-lg text-chalk mb-4">Pit Strategy</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div><label className={labelCls}>Min Pit Stop (s)</label><input type="number" className={inputCls} value={minPitStop} onChange={e => setMinPitStop(e.target.value)} /></div>
            <div><label className={labelCls}>Pit Speed (km/h)</label><input type="number" className={inputCls} value={pitSpeed} onChange={e => setPitSpeed(e.target.value)} step="0.1" /></div>
            <div><label className={labelCls}>Quick Pit Stop (s)</label><input type="number" className={inputCls} value={quickPitStop} onChange={e => setQuickPitStop(e.target.value)} /></div>
          </div>
          <div className="flex gap-6 mt-4">
            <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
              <input type="checkbox" checked={mandatoryChange} onChange={e => setMandatoryChange(e.target.checked)} className="accent-pit-orange" />
              Mandatory driver change
            </label>
            <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
              <input type="checkbox" checked={refuelingAllowed} onChange={e => setRefuelingAllowed(e.target.checked)} className="accent-pit-orange" />
              Refueling allowed
            </label>
          </div>
        </div>

        {/* Pit Windows */}
        <div className={sectionCls}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-monument text-lg text-chalk">Pit Windows</h2>
            <button type="button" onClick={addWindow} className="px-3 py-1 text-sm font-telemetry text-pit-orange border border-pit-orange/40 hover:bg-pit-orange/10 transition-colors">
              + Add Window
            </button>
          </div>
          {windows.length === 0 ? (
            <p className="text-steel font-body text-sm">No pit windows configured. The pit lane is open for the entire race.</p>
          ) : (
            <div className="space-y-3">
              {windows.map((w, i) => (
                <div key={i} className="flex items-center gap-3 bg-asphalt/40 border border-steel/10 p-3">
                  <select className={`${inputCls} w-32`} value={w.window_type} onChange={e => updateWindow(i, 'window_type', e.target.value)}>
                    <option value="pitlane">Pit Lane</option>
                    <option value="refuel">Refuel</option>
                    <option value="tech_stop">Tech Stop</option>
                  </select>
                  <input className={`${inputCls} w-32`} value={w.label} onChange={e => updateWindow(i, 'label', e.target.value)} placeholder="Label" />
                  <div className="flex items-center gap-1">
                    <input type="number" className={`${inputCls} w-16`} value={w.start_mm} onChange={e => updateWindow(i, 'start_mm', e.target.value)} min="0" />
                    <span className="text-steel">:</span>
                    <input type="number" className={`${inputCls} w-16`} value={w.start_ss} onChange={e => updateWindow(i, 'start_ss', e.target.value)} min="0" max="59" />
                  </div>
                  <span className="text-steel">→</span>
                  <div className="flex items-center gap-1">
                    <input type="number" className={`${inputCls} w-16`} value={w.end_mm} onChange={e => updateWindow(i, 'end_mm', e.target.value)} min="0" />
                    <span className="text-steel">:</span>
                    <input type="number" className={`${inputCls} w-16`} value={w.end_ss} onChange={e => updateWindow(i, 'end_ss', e.target.value)} min="0" max="59" />
                  </div>
                  <button type="button" onClick={() => removeWindow(i)} className="text-safety-red hover:text-safety-red/80 text-sm">✕</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Fuel & Weight */}
        <div className={sectionCls}>
          <h2 className="font-monument text-lg text-chalk mb-4">Fuel & Weight</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <label className={labelCls}>Fuel Autonomy</label>
              <div className="flex items-center gap-1">
                <input type="number" className={`${inputCls} w-20`} value={fuelAutonomyM} onChange={e => setFuelAutonomyM(e.target.value)} placeholder="mm" min="0" />
                <span className="text-steel">:</span>
                <input type="number" className={`${inputCls} w-20`} value={fuelAutonomyS} onChange={e => setFuelAutonomyS(e.target.value)} placeholder="ss" min="0" max="59" />
              </div>
            </div>
            <div><label className={labelCls}>Empty Kart (kg)</label><input type="number" className={inputCls} value={emptyKart} onChange={e => setEmptyKart(e.target.value)} step="0.1" /></div>
            <div><label className={labelCls}>Full Tank (kg)</label><input type="number" className={inputCls} value={fullTank} onChange={e => setFullTank(e.target.value)} step="0.1" /></div>
            <div><label className={labelCls}>Min Total (kg)</label><input type="number" className={inputCls} value={minTotal} onChange={e => setMinTotal(e.target.value)} step="0.1" /></div>
            <div><label className={labelCls}>Reference Weight (kg)</label><input type="number" className={inputCls} value={referenceWeight} onChange={e => setReferenceWeight(e.target.value)} step="0.1" /></div>
            <div className="flex items-end pb-2">
              <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                <input type="checkbox" checked={weighOnExit} onChange={e => setWeighOnExit(e.target.checked)} className="accent-pit-orange" />
                Weigh on pit exit
              </label>
            </div>
          </div>
        </div>

        {/* Qualifying */}
        <div className={sectionCls}>
          <button type="button" onClick={() => setShowQuali(!showQuali)} className="flex items-center gap-2 font-monument text-lg text-chalk">
            {showQuali ? '▼' : '▶'} Qualifying
          </button>
          {showQuali && (
            <div className="grid grid-cols-2 gap-4 mt-4">
              <div><label className={labelCls}>Duration (s)</label><input type="number" className={inputCls} value={qualiDuration} onChange={e => setQualiDuration(e.target.value)} /></div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                  <input type="checkbox" checked={refuelAfterQuali} onChange={e => setRefuelAfterQuali(e.target.checked)} className="accent-pit-orange" />
                  Refuel after qualifying
                </label>
              </div>
            </div>
          )}
        </div>

        {/* Submit */}
        <div className="flex items-center gap-4 mt-6">
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-6 py-3 bg-pit-orange text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-pit-orange/80 transition-colors disabled:opacity-50"
          >
            {mutation.isPending ? 'Creating...' : 'Create Race'}
          </button>
          <button
            type="button"
            onClick={() => router.back()}
            className="px-6 py-3 border border-steel/30 text-steel font-telemetry text-sm tracking-wider uppercase hover:text-chalk hover:border-chalk/30 transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
