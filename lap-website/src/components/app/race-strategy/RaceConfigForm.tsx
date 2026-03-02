'use client';

import { useState, useEffect, useId } from 'react';
import { UpgradeBanner } from '@/components/billing/UpgradeBanner';

/* ------------------------------------------------------------------ */
/*  Shared types                                                       */
/* ------------------------------------------------------------------ */

export interface DriverForm {
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

export interface WindowForm {
  window_type: string;
  label: string;
  start_mm: string;
  start_ss: string;
  end_mm: string;
  end_ss: string;
  refuel_allowed: boolean;
  driver_change_allowed: boolean;
}

/** Payload shape assembled by the form and passed to onSubmit. */
export interface RaceFormData {
  race: {
    race_name: string;
    team_name: string | null;
    track_name: string | null;
    race_duration_s: number;
    desired_stints: number;
    min_pit_stop_s: number;
    pit_speed_kmh: number | null;
    quick_pit_stop_s: number | null;
    mandatory_driver_change: number;
    refueling_allowed: number;
    fuel_autonomy_s: number | null;
    empty_kart_kg: number | null;
    full_tank_kg: number | null;
    min_total_kart_kg: number | null;
    reference_weight_kg: number | null;
    weigh_on_pit_exit: number;
    qualifying_duration_s: number | null;
    refuel_after_quali: number;
  };
  drivers: Array<{
    driver_name: string;
    driver_order: number;
    weight_kg: number | null;
    com_channel: string | null;
    color_hex: string;
    min_stint_s: number | null;
    max_stint_s: number | null;
    min_cumulative_s: number | null;
    max_cumulative_s: number | null;
    min_rest_s: number;
  }>;
  windows: Array<{
    window_type: string;
    label: string | null;
    start_s: number;
    end_s: number;
    refuel_allowed: number;
    driver_change_allowed: number;
    window_order: number;
  }>;
}

/* ------------------------------------------------------------------ */
/*  Shared helpers                                                     */
/* ------------------------------------------------------------------ */

export const DRIVER_COLORS = [
  '#3B82F6', '#EF4444', '#10B981', '#F59E0B',
  '#8B5CF6', '#EC4899', '#06B6D4', '#F97316',
];

export function mmssToSeconds(mm: string, ss: string): number {
  return (parseInt(mm) || 0) * 60 + (parseInt(ss) || 0);
}

export function secondsToMM(s: number | null): string {
  return s != null ? String(Math.floor(s / 60)) : '';
}

export function secondsToSS(s: number | null): string {
  return s != null ? String(s % 60) : '';
}

export function parseNum(v: string): number | null {
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

export function str(v: unknown): string {
  return v != null ? String(v) : '';
}

/* ------------------------------------------------------------------ */
/*  Defaults & style tokens                                            */
/* ------------------------------------------------------------------ */

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

const inputCls =
  'w-full bg-asphalt border border-steel/30 px-3 py-2 text-chalk font-body text-sm focus:border-pit-orange focus:outline-none';
const labelCls =
  'block text-steel font-telemetry text-[11px] tracking-[0.08em] uppercase mb-1';
const sectionCls = 'bg-concrete border border-steel/20 p-5 mb-4';

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

export interface RaceConfigFormProps {
  mode: 'create' | 'edit';
  initialData?: {
    race: Record<string, unknown>;
    drivers: Array<Record<string, unknown>>;
    windows: Array<Record<string, unknown>>;
  };
  /** Entitlement value, e.g. 'limited_3h' for demo plans. */
  raceStrategyLimit?: string | null;
  onSubmit: (data: RaceFormData) => void;
  onCancel?: () => void;
  isSubmitting: boolean;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function RaceConfigForm({
  mode,
  initialData,
  raceStrategyLimit,
  onSubmit,
  onCancel,
  isSubmitting,
}: RaceConfigFormProps) {
  const fieldId = useId();
  const [error, setError] = useState('');

  /* ---- form state ---- */
  const [raceName, setRaceName] = useState('');
  const [teamName, setTeamName] = useState('');
  const [trackName, setTrackName] = useState('');
  const [durationH, setDurationH] = useState('3');
  const [durationM, setDurationM] = useState('0');
  const [desiredStints, setDesiredStints] = useState('4');

  const [drivers, setDrivers] = useState<DriverForm[]>(
    mode === 'create'
      ? [
          { ...DEFAULT_DRIVER, color_hex: DRIVER_COLORS[0] },
          { ...DEFAULT_DRIVER, color_hex: DRIVER_COLORS[1] },
        ]
      : [],
  );

  const [minPitStop, setMinPitStop] = useState('60');
  const [pitSpeed, setPitSpeed] = useState('');
  const [quickPitStop, setQuickPitStop] = useState('');
  const [mandatoryChange, setMandatoryChange] = useState(true);
  const [refuelingAllowed, setRefuelingAllowed] = useState(true);

  const [windows, setWindows] = useState<WindowForm[]>([]);

  const [fuelAutonomyM, setFuelAutonomyM] = useState('');
  const [fuelAutonomyS, setFuelAutonomyS] = useState('');
  const [emptyKart, setEmptyKart] = useState('');
  const [fullTank, setFullTank] = useState('');
  const [minTotal, setMinTotal] = useState('');
  const [referenceWeight, setReferenceWeight] = useState('');
  const [weighOnExit, setWeighOnExit] = useState(false);

  const [showQuali, setShowQuali] = useState(false);
  const [qualiDuration, setQualiDuration] = useState('');
  const [refuelAfterQuali, setRefuelAfterQuali] = useState(false);

  /* ---- populate from initialData (edit mode) ---- */
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (mode !== 'edit' || !initialData || loaded) return;
    const r = initialData.race;

    setRaceName(str(r.race_name));
    setTeamName(str(r.team_name));
    setTrackName(str(r.track_name));

    const dur = Number(r.race_duration_s) || 0;
    setDurationH(String(Math.floor(dur / 3600)));
    setDurationM(String(Math.floor((dur % 3600) / 60)));
    setDesiredStints(str(r.desired_stints) || '4');

    setMinPitStop(str(r.min_pit_stop_s) || '60');
    setPitSpeed(str(r.pit_speed_kmh));
    setQuickPitStop(str(r.quick_pit_stop_s));
    setMandatoryChange(!!r.mandatory_driver_change);
    setRefuelingAllowed(!!r.refueling_allowed);

    const fa = Number(r.fuel_autonomy_s) || 0;
    setFuelAutonomyM(fa > 0 ? secondsToMM(fa) : '');
    setFuelAutonomyS(fa > 0 ? secondsToSS(fa) : '');
    setEmptyKart(str(r.empty_kart_kg));
    setFullTank(str(r.full_tank_kg));
    setMinTotal(str(r.min_total_kart_kg));
    setReferenceWeight(str(r.reference_weight_kg));
    setWeighOnExit(!!r.weigh_on_pit_exit);

    if (r.qualifying_duration_s) {
      setShowQuali(true);
      setQualiDuration(str(r.qualifying_duration_s));
    }
    setRefuelAfterQuali(!!r.refuel_after_quali);

    setDrivers(
      initialData.drivers.map((d, i) => ({
        driver_name: str(d.driver_name),
        weight_kg: str(d.weight_kg),
        com_channel: str(d.com_channel),
        color_hex: str(d.color_hex) || DRIVER_COLORS[i % DRIVER_COLORS.length],
        min_stint_s: str(d.min_stint_s),
        max_stint_s: str(d.max_stint_s),
        min_cumulative_s: str(d.min_cumulative_s),
        max_cumulative_s: str(d.max_cumulative_s),
        min_rest_s: str(d.min_rest_s),
        showConstraints: false,
      })),
    );

    setWindows(
      initialData.windows.map((w) => ({
        window_type: str(w.window_type) || 'pitlane',
        label: str(w.label),
        start_mm: secondsToMM(Number(w.start_s) || 0),
        start_ss: secondsToSS(Number(w.start_s) || 0),
        end_mm: secondsToMM(Number(w.end_s) || 0),
        end_ss: secondsToSS(Number(w.end_s) || 0),
        refuel_allowed: !!w.refuel_allowed,
        driver_change_allowed: !!w.driver_change_allowed,
      })),
    );

    setLoaded(true);
  }, [mode, initialData, loaded]);

  /* ---- driver / window helpers ---- */
  function addDriver() {
    setDrivers((prev) => [
      ...prev,
      { ...DEFAULT_DRIVER, color_hex: DRIVER_COLORS[prev.length % DRIVER_COLORS.length] },
    ]);
  }
  function removeDriver(idx: number) {
    setDrivers((prev) => prev.filter((_, i) => i !== idx));
  }
  function updateDriver(idx: number, field: keyof DriverForm, value: string | boolean) {
    setDrivers((prev) => prev.map((d, i) => (i === idx ? { ...d, [field]: value } : d)));
  }
  function addWindow() {
    setWindows((prev) => [...prev, { ...DEFAULT_WINDOW }]);
  }
  function removeWindow(idx: number) {
    setWindows((prev) => prev.filter((_, i) => i !== idx));
  }
  function updateWindow(idx: number, field: keyof WindowForm, value: string | boolean) {
    setWindows((prev) => prev.map((w, i) => (i === idx ? { ...w, [field]: value } : w)));
  }

  /* ---- submit ---- */
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    const raceDurationS = (parseInt(durationH) || 0) * 3600 + (parseInt(durationM) || 0) * 60;
    if (!raceName.trim()) {
      setError('Race name is required');
      return;
    }
    if (raceDurationS <= 0) {
      setError('Race duration must be positive');
      return;
    }
    if (drivers.filter((d) => d.driver_name.trim()).length < 1) {
      setError('At least one driver is required');
      return;
    }

    const payload: RaceFormData = {
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
        .filter((d) => d.driver_name.trim())
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

    onSubmit(payload);
  }

  /* ---- render ---- */
  return (
    <>
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
              <label htmlFor={`${fieldId}-race-name`} className={labelCls}>Race Name *</label>
              <input id={`${fieldId}-race-name`} className={inputCls} value={raceName} onChange={(e) => setRaceName(e.target.value)} placeholder="24h Le Mans Kart" />
            </div>
            <div>
              <label htmlFor={`${fieldId}-team-name`} className={labelCls}>Team Name</label>
              <input id={`${fieldId}-team-name`} className={inputCls} value={teamName} onChange={(e) => setTeamName(e.target.value)} placeholder="Apex Racing" />
            </div>
            <div>
              <label htmlFor={`${fieldId}-track`} className={labelCls}>Track</label>
              <input id={`${fieldId}-track`} className={inputCls} value={trackName} onChange={(e) => setTrackName(e.target.value)} placeholder="Circuit de Pau-Arnos" />
            </div>
            <div>
              {raceStrategyLimit === 'limited_3h' && (
                <div className="mb-3">
                  <UpgradeBanner
                    feature="race_strategy_full"
                    context="Demo plan: races limited to 3 hours. Upgrade for unlimited duration."
                  />
                </div>
              )}
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label htmlFor={`${fieldId}-dur-h`} className={labelCls}>Duration (h)</label>
                  <input id={`${fieldId}-dur-h`} type="number" className={inputCls} value={durationH} onChange={(e) => setDurationH(e.target.value)} min="0" />
                </div>
                <div>
                  <label htmlFor={`${fieldId}-dur-m`} className={labelCls}>Minutes</label>
                  <input id={`${fieldId}-dur-m`} type="number" className={inputCls} value={durationM} onChange={(e) => setDurationM(e.target.value)} min="0" max="59" />
                </div>
                <div>
                  <label htmlFor={`${fieldId}-stints`} className={labelCls}>Stints</label>
                  <input id={`${fieldId}-stints`} type="number" className={inputCls} value={desiredStints} onChange={(e) => setDesiredStints(e.target.value)} min="1" />
                </div>
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
                  <input type="color" aria-label={`Driver ${i + 1} color`} value={d.color_hex} onChange={(e) => updateDriver(i, 'color_hex', e.target.value)} className="w-8 h-8 rounded cursor-pointer bg-transparent border-0" />
                  <input aria-label={`Driver ${i + 1} name`} className={`${inputCls} flex-1 min-w-[12rem]`} value={d.driver_name} onChange={(e) => updateDriver(i, 'driver_name', e.target.value)} placeholder="Driver name" />
                  <input aria-label={`Driver ${i + 1} weight (kg)`} className={`${inputCls} w-24`} value={d.weight_kg} onChange={(e) => updateDriver(i, 'weight_kg', e.target.value)} placeholder="kg" type="number" step="0.1" />
                  <input aria-label={`Driver ${i + 1} COM channel`} className={`${inputCls} w-24`} value={d.com_channel} onChange={(e) => updateDriver(i, 'com_channel', e.target.value)} placeholder="COM" />
                  <button type="button" aria-label={`Toggle driver ${i + 1} constraints`} onClick={() => updateDriver(i, 'showConstraints', !d.showConstraints)} className="text-steel hover:text-chalk text-xs font-telemetry transition-colors">
                    {d.showConstraints ? '\u25BC' : '\u25B6'} Rules
                  </button>
                  {drivers.length > 1 && (
                    <button type="button" onClick={() => removeDriver(i)} aria-label={`Remove driver ${i + 1}`} className="text-safety-red hover:text-safety-red/80 text-sm transition-colors">{'\u2715'}</button>
                  )}
                </div>
                {d.showConstraints && (
                  <div className="grid grid-cols-5 gap-2 mt-2 pl-11">
                    <div><label htmlFor={`${fieldId}-d${i}-min-stint`} className={labelCls}>Min stint(s)</label><input id={`${fieldId}-d${i}-min-stint`} className={inputCls} value={d.min_stint_s} onChange={(e) => updateDriver(i, 'min_stint_s', e.target.value)} type="number" /></div>
                    <div><label htmlFor={`${fieldId}-d${i}-max-stint`} className={labelCls}>Max stint(s)</label><input id={`${fieldId}-d${i}-max-stint`} className={inputCls} value={d.max_stint_s} onChange={(e) => updateDriver(i, 'max_stint_s', e.target.value)} type="number" /></div>
                    <div><label htmlFor={`${fieldId}-d${i}-min-total`} className={labelCls}>Min total(s)</label><input id={`${fieldId}-d${i}-min-total`} className={inputCls} value={d.min_cumulative_s} onChange={(e) => updateDriver(i, 'min_cumulative_s', e.target.value)} type="number" /></div>
                    <div><label htmlFor={`${fieldId}-d${i}-max-total`} className={labelCls}>Max total(s)</label><input id={`${fieldId}-d${i}-max-total`} className={inputCls} value={d.max_cumulative_s} onChange={(e) => updateDriver(i, 'max_cumulative_s', e.target.value)} type="number" /></div>
                    <div><label htmlFor={`${fieldId}-d${i}-min-rest`} className={labelCls}>Min rest(s)</label><input id={`${fieldId}-d${i}-min-rest`} className={inputCls} value={d.min_rest_s} onChange={(e) => updateDriver(i, 'min_rest_s', e.target.value)} type="number" /></div>
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
            <div><label htmlFor={`${fieldId}-min-pit`} className={labelCls}>Min Pit Stop (s)</label><input id={`${fieldId}-min-pit`} type="number" className={inputCls} value={minPitStop} onChange={(e) => setMinPitStop(e.target.value)} /></div>
            <div><label htmlFor={`${fieldId}-pit-speed`} className={labelCls}>Pit Speed (km/h)</label><input id={`${fieldId}-pit-speed`} type="number" className={inputCls} value={pitSpeed} onChange={(e) => setPitSpeed(e.target.value)} step="0.1" /></div>
            <div><label htmlFor={`${fieldId}-quick-pit`} className={labelCls}>Quick Pit Stop (s)</label><input id={`${fieldId}-quick-pit`} type="number" className={inputCls} value={quickPitStop} onChange={(e) => setQuickPitStop(e.target.value)} /></div>
          </div>
          <div className="flex gap-6 mt-4">
            <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
              <input type="checkbox" checked={mandatoryChange} onChange={(e) => setMandatoryChange(e.target.checked)} className="accent-pit-orange" />
              Mandatory driver change
            </label>
            <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
              <input type="checkbox" checked={refuelingAllowed} onChange={(e) => setRefuelingAllowed(e.target.checked)} className="accent-pit-orange" />
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
                  <select aria-label={`Window ${i + 1} type`} className={`${inputCls} w-32`} value={w.window_type} onChange={(e) => updateWindow(i, 'window_type', e.target.value)}>
                    <option value="pitlane">Pit Lane</option>
                    <option value="refuel">Refuel</option>
                    <option value="tech_stop">Tech Stop</option>
                  </select>
                  <input aria-label={`Window ${i + 1} label`} className={`${inputCls} w-32`} value={w.label} onChange={(e) => updateWindow(i, 'label', e.target.value)} placeholder="Label" />
                  <div className="flex items-center gap-1">
                    <input aria-label={`Window ${i + 1} start minutes`} type="number" className={`${inputCls} w-16`} value={w.start_mm} onChange={(e) => updateWindow(i, 'start_mm', e.target.value)} min="0" />
                    <span className="text-steel">:</span>
                    <input aria-label={`Window ${i + 1} start seconds`} type="number" className={`${inputCls} w-16`} value={w.start_ss} onChange={(e) => updateWindow(i, 'start_ss', e.target.value)} min="0" max="59" />
                  </div>
                  <span className="text-steel">{'\u2192'}</span>
                  <div className="flex items-center gap-1">
                    <input aria-label={`Window ${i + 1} end minutes`} type="number" className={`${inputCls} w-16`} value={w.end_mm} onChange={(e) => updateWindow(i, 'end_mm', e.target.value)} min="0" />
                    <span className="text-steel">:</span>
                    <input aria-label={`Window ${i + 1} end seconds`} type="number" className={`${inputCls} w-16`} value={w.end_ss} onChange={(e) => updateWindow(i, 'end_ss', e.target.value)} min="0" max="59" />
                  </div>
                  <button type="button" onClick={() => removeWindow(i)} aria-label={`Remove window ${i + 1}`} className="text-safety-red hover:text-safety-red/80 text-sm transition-colors">{'\u2715'}</button>
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
                <input aria-label="Fuel autonomy minutes" type="number" className={`${inputCls} w-20`} value={fuelAutonomyM} onChange={(e) => setFuelAutonomyM(e.target.value)} placeholder="mm" min="0" />
                <span className="text-steel">:</span>
                <input aria-label="Fuel autonomy seconds" type="number" className={`${inputCls} w-20`} value={fuelAutonomyS} onChange={(e) => setFuelAutonomyS(e.target.value)} placeholder="ss" min="0" max="59" />
              </div>
            </div>
            <div><label htmlFor={`${fieldId}-empty-kart`} className={labelCls}>Empty Kart (kg)</label><input id={`${fieldId}-empty-kart`} type="number" className={inputCls} value={emptyKart} onChange={(e) => setEmptyKart(e.target.value)} step="0.1" /></div>
            <div><label htmlFor={`${fieldId}-full-tank`} className={labelCls}>Full Tank (kg)</label><input id={`${fieldId}-full-tank`} type="number" className={inputCls} value={fullTank} onChange={(e) => setFullTank(e.target.value)} step="0.1" /></div>
            <div><label htmlFor={`${fieldId}-min-total-kg`} className={labelCls}>Min Total (kg)</label><input id={`${fieldId}-min-total-kg`} type="number" className={inputCls} value={minTotal} onChange={(e) => setMinTotal(e.target.value)} step="0.1" /></div>
            <div><label htmlFor={`${fieldId}-ref-weight`} className={labelCls}>Reference Weight (kg)</label><input id={`${fieldId}-ref-weight`} type="number" className={inputCls} value={referenceWeight} onChange={(e) => setReferenceWeight(e.target.value)} step="0.1" /></div>
            <div className="flex items-end pb-2">
              <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                <input type="checkbox" checked={weighOnExit} onChange={(e) => setWeighOnExit(e.target.checked)} className="accent-pit-orange" />
                Weigh on pit exit
              </label>
            </div>
          </div>
        </div>

        {/* Qualifying */}
        <div className={sectionCls}>
          <button type="button" aria-label="Toggle qualifying section" onClick={() => setShowQuali(!showQuali)} className="flex items-center gap-2 font-monument text-lg text-chalk">
            {showQuali ? '\u25BC' : '\u25B6'} Qualifying
          </button>
          {showQuali && (
            <div className="grid grid-cols-2 gap-4 mt-4">
              <div><label htmlFor={`${fieldId}-quali-dur`} className={labelCls}>Duration (s)</label><input id={`${fieldId}-quali-dur`} type="number" className={inputCls} value={qualiDuration} onChange={(e) => setQualiDuration(e.target.value)} /></div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                  <input type="checkbox" checked={refuelAfterQuali} onChange={(e) => setRefuelAfterQuali(e.target.checked)} className="accent-pit-orange" />
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
            disabled={isSubmitting}
            className="px-6 py-3 bg-pit-orange text-asphalt font-telemetry text-sm tracking-wider uppercase hover:bg-pit-orange/80 transition-colors disabled:opacity-50"
          >
            {isSubmitting
              ? mode === 'create' ? 'Creating...' : 'Saving...'
              : mode === 'create' ? 'Create Race' : 'Save Changes'}
          </button>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="px-6 py-3 border border-steel/30 text-steel font-telemetry text-sm tracking-wider uppercase hover:text-chalk hover:border-chalk/30 transition-colors"
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </>
  );
}
