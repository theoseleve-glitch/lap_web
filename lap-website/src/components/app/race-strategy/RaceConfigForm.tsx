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
  allow_double_stint: boolean;
  avg_lap_time_s: string;
  wet_confidence: string;
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

export interface SleepWindowForm {
  driver_index: string;  // index into drivers array (we don't have DB IDs during creation)
  start_hh: string;
  start_mm: string;
  end_hh: string;
  end_mm: string;
  label: string;
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
    optimization_mode: 'equal' | 'performance';
    blackout_start_min: number | null;
    blackout_end_min: number | null;
    quick_change_enabled: number;
    tech_stop_enabled: number;
    tech_stop_duration_s: number;
    tech_stop_window_start_s: number | null;
    tech_stop_window_end_s: number | null;
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
    allow_double_stint: boolean;
    avg_lap_time_s: number | null;
    wet_confidence: number;
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
  sleep_windows: Array<{
    driver_id: number;
    start_s: number;
    end_s: number;
    label: string | null;
  }>;
  weather_windows?: Array<{
    start_s: number;
    end_s: number;
    condition: string;
    confidence_pct: number;
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
  allow_double_stint: false,
  avg_lap_time_s: '',
  wet_confidence: '50',
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
/*  Duration mm:ss input                                               */
/* ------------------------------------------------------------------ */

function DurationMmSs({ value, onChange, id, label }: {
  value: string;
  onChange: (v: string) => void;
  id: string;
  label: string;
}) {
  const totalS = parseInt(value) || 0;
  const hasValue = value !== '' && value != null;

  return (
    <div className="flex items-center gap-1">
      <input
        id={id}
        type="number"
        aria-label={`${label} minutes`}
        className={`${inputCls} w-12 text-center`}
        value={hasValue ? Math.floor(totalS / 60) : ''}
        onChange={(e) => {
          const mm = parseInt(e.target.value) || 0;
          const ss = hasValue ? totalS % 60 : 0;
          onChange(e.target.value === '' && ss === 0 ? '' : String(mm * 60 + ss));
        }}
        min="0"
        placeholder="m"
      />
      <span className="text-steel/60 text-xs font-telemetry">:</span>
      <input
        type="number"
        aria-label={`${label} seconds`}
        className={`${inputCls} w-12 text-center`}
        value={hasValue ? totalS % 60 : ''}
        onChange={(e) => {
          const ss = Math.min(59, parseInt(e.target.value) || 0);
          const mm = hasValue ? Math.floor(totalS / 60) : 0;
          onChange(e.target.value === '' && mm === 0 ? '' : String(mm * 60 + ss));
        }}
        min="0"
        max="59"
        placeholder="s"
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Props                                                              */
/* ------------------------------------------------------------------ */

export interface RaceConfigFormProps {
  mode: 'create' | 'edit';
  initialData?: {
    race: Record<string, unknown>;
    drivers: Array<Record<string, unknown>>;
    windows: Array<Record<string, unknown>>;
    sleep_windows?: Array<Record<string, unknown>>;
  };
  /** Entitlement value, e.g. '4h_simple', '12h_complex', 'unlimited'. */
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

  const isDemo = raceStrategyLimit === '4h_basic';
  const isComplex = raceStrategyLimit === '24h_complex' || raceStrategyLimit === 'unlimited';

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
  const [sleepWindows, setSleepWindows] = useState<SleepWindowForm[]>([]);
  const [weatherWindows, setWeatherWindows] = useState<Array<{
    startH: string; startM: string; endH: string; endM: string;
    condition: string; confidence: string;
  }>>([]);

  const raceDurationS = (parseInt(durationH) || 0) * 3600 + (parseInt(durationM) || 0) * 60;
  const isEndurance = raceDurationS >= 43200;

  const [fuelAutonomyM, setFuelAutonomyM] = useState('');
  const [fuelAutonomyS, setFuelAutonomyS] = useState('');
  const [emptyKart, setEmptyKart] = useState('');
  const [fullTank, setFullTank] = useState('');
  const [minTotal, setMinTotal] = useState('');
  const [weighOnExit, setWeighOnExit] = useState(false);

  const [showQuali, setShowQuali] = useState(false);
  const [qualiDuration, setQualiDuration] = useState('');
  const [refuelAfterQuali, setRefuelAfterQuali] = useState(false);

  /* ---- default driver rules ---- */
  const [defaultMinStint, setDefaultMinStint] = useState('');
  const [defaultMaxStint, setDefaultMaxStint] = useState('');
  const [defaultMinTotal, setDefaultMinTotal] = useState('');
  const [defaultMaxTotal, setDefaultMaxTotal] = useState('');
  const [defaultMinRest, setDefaultMinRest] = useState('');
  const [defaultAllowDouble, setDefaultAllowDouble] = useState(false);
  const [showDefaultRules, setShowDefaultRules] = useState(false);

  /* ---- optimization & advanced pit ---- */
  const [optimizationMode, setOptimizationMode] = useState<'equal' | 'performance'>('equal');
  const [blackoutStart, setBlackoutStart] = useState('');
  const [blackoutEnd, setBlackoutEnd] = useState('');
  const [quickChange, setQuickChange] = useState(false);

  /* ---- tech stop ---- */
  const [techStopEnabled, setTechStopEnabled] = useState(false);
  const [techStopDuration, setTechStopDuration] = useState('300');
  const [techStopWindowStart, setTechStopWindowStart] = useState('');
  const [techStopWindowEnd, setTechStopWindowEnd] = useState('');

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
    setWeighOnExit(!!r.weigh_on_pit_exit);

    if (r.qualifying_duration_s) {
      setShowQuali(true);
      setQualiDuration(str(r.qualifying_duration_s));
    }
    setRefuelAfterQuali(!!r.refuel_after_quali);

    /* new fields */
    setOptimizationMode(((r as any).optimization_mode === 'performance' ? 'performance' : 'equal'));
    setBlackoutStart(str((r as any).blackout_start_min));
    setBlackoutEnd(str((r as any).blackout_end_min));
    setQuickChange(!!(r as any).quick_change_enabled);
    setTechStopEnabled(!!(r as any).tech_stop_enabled);
    setTechStopDuration(str((r as any).tech_stop_duration_s) || '300');
    setTechStopWindowStart(str((r as any).tech_stop_window_start_s));
    setTechStopWindowEnd(str((r as any).tech_stop_window_end_s));

    // Default driver rules
    if ((r as any).default_min_stint_s) setDefaultMinStint(str((r as any).default_min_stint_s));
    if ((r as any).default_max_stint_s) setDefaultMaxStint(str((r as any).default_max_stint_s));
    if ((r as any).default_min_cumulative_s) setDefaultMinTotal(str((r as any).default_min_cumulative_s));
    if ((r as any).default_max_cumulative_s) setDefaultMaxTotal(str((r as any).default_max_cumulative_s));
    if ((r as any).default_min_rest_s) setDefaultMinRest(str((r as any).default_min_rest_s));
    setDefaultAllowDouble(!!(r as any).default_allow_double);
    if ((r as any).default_min_stint_s || (r as any).default_max_stint_s) setShowDefaultRules(true);

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
        allow_double_stint: !!(d as any).allow_double_stint,
        avg_lap_time_s: str((d as any).avg_lap_time_s),
        wet_confidence: str((d as any).wet_confidence ? String(Math.round((d as any).wet_confidence * 100)) : '50'),
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

    if (initialData.sleep_windows) {
      // Map DB driver_id back to 0-based index in the drivers array
      const driverIdToIndex: Record<number, number> = {};
      initialData.drivers.forEach((d, idx) => {
        const did = (d as Record<string, unknown>).id ?? (d as Record<string, unknown>).driver_id;
        if (did != null) driverIdToIndex[Number(did)] = idx;
      });
      setSleepWindows(
        initialData.sleep_windows.map((sw) => {
          const startS = Number(sw.start_s) || 0;
          const endS = Number(sw.end_s) || 0;
          const dbDriverId = Number(sw.driver_id) || 0;
          const idx = driverIdToIndex[dbDriverId] ?? '';
          return {
            driver_index: String(idx),
            start_hh: String(Math.floor(startS / 3600)),
            start_mm: String(Math.floor((startS % 3600) / 60)),
            end_hh: String(Math.floor(endS / 3600)),
            end_mm: String(Math.floor((endS % 3600) / 60)),
            label: str(sw.label),
          };
        }),
      );
    }

    if ((initialData as any).weather_windows) {
      setWeatherWindows(
        ((initialData as any).weather_windows || []).map((w: any) => ({
          startH: String(Math.floor((w.start_s || 0) / 3600)),
          startM: String(Math.floor(((w.start_s || 0) % 3600) / 60)),
          endH: String(Math.floor((w.end_s || 0) / 3600)),
          endM: String(Math.floor(((w.end_s || 0) % 3600) / 60)),
          condition: w.condition || 'wet',
          confidence: String(w.confidence_pct || 100),
        }))
      );
    }

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
  function updateSleepWindow(idx: number, field: keyof SleepWindowForm, value: string) {
    setSleepWindows((prev) => prev.map((sw, i) => (i === idx ? { ...sw, [field]: value } : sw)));
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
        reference_weight_kg: null,
        weigh_on_pit_exit: weighOnExit ? 1 : 0,
        qualifying_duration_s: parseNum(qualiDuration),
        refuel_after_quali: refuelAfterQuali ? 1 : 0,
        optimization_mode: optimizationMode,
        blackout_start_min: parseNum(blackoutStart),
        blackout_end_min: parseNum(blackoutEnd),
        quick_change_enabled: quickChange ? 1 : 0,
        tech_stop_enabled: techStopEnabled ? 1 : 0,
        tech_stop_duration_s: parseInt(techStopDuration) || 300,
        tech_stop_window_start_s: parseNum(techStopWindowStart),
        tech_stop_window_end_s: parseNum(techStopWindowEnd),
        default_min_stint_s: parseNum(defaultMinStint),
        default_max_stint_s: parseNum(defaultMaxStint),
        default_min_cumulative_s: parseNum(defaultMinTotal),
        default_max_cumulative_s: parseNum(defaultMaxTotal),
        default_min_rest_s: parseNum(defaultMinRest),
        default_allow_double: defaultAllowDouble ? 1 : 0,
      },
      drivers: drivers
        .filter((d) => d.driver_name.trim())
        .map((d, i) => ({
          driver_name: d.driver_name.trim(),
          driver_order: i + 1,
          weight_kg: parseNum(d.weight_kg),
          com_channel: d.com_channel.trim() || null,
          color_hex: d.color_hex,
          min_stint_s: parseNum(d.min_stint_s) ?? parseNum(defaultMinStint),
          max_stint_s: parseNum(d.max_stint_s) ?? parseNum(defaultMaxStint),
          min_cumulative_s: parseNum(d.min_cumulative_s) ?? parseNum(defaultMinTotal),
          max_cumulative_s: parseNum(d.max_cumulative_s) ?? parseNum(defaultMaxTotal),
          min_rest_s: parseNum(d.min_rest_s) ?? parseNum(defaultMinRest) ?? 0,
          allow_double_stint: d.showConstraints ? d.allow_double_stint : defaultAllowDouble,
          avg_lap_time_s: parseNum(d.avg_lap_time_s),
          wet_confidence: (parseNum(d.wet_confidence) ?? 50) / 100,
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
      sleep_windows: sleepWindows
        .filter(sw => sw.driver_index !== '' && sw.start_hh !== '' && sw.end_hh !== '')
        .map(sw => ({
          driver_id: parseInt(sw.driver_index),
          start_s: parseInt(sw.start_hh) * 3600 + parseInt(sw.start_mm || '0') * 60,
          end_s: parseInt(sw.end_hh) * 3600 + parseInt(sw.end_mm || '0') * 60,
          label: sw.label || null,
        })),
      weather_windows: weatherWindows
        .filter(w => w.startH !== '' && w.endH !== '')
        .map(w => ({
          start_s: parseInt(w.startH || '0') * 3600 + parseInt(w.startM || '0') * 60,
          end_s: parseInt(w.endH || '0') * 3600 + parseInt(w.endM || '0') * 60,
          condition: w.condition,
          confidence_pct: parseInt(w.confidence || '100'),
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
        {/* Upgrade banners */}
        {isDemo && (
          <div className="mb-4">
            <UpgradeBanner
              feature="race_strategy_complex"
              context="Demo plan: races up to 4 hours. Upgrade for 24-hour races and advanced features."
            />
          </div>
        )}
        {isComplex && raceStrategyLimit !== 'unlimited' && (
          <div className="mb-4">
            <UpgradeBanner
              feature="race_strategy_full"
              context="Racer plan: races up to 24 hours. Upgrade to World-Class for unlimited duration."
            />
          </div>
        )}

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

          {/* Default Driver Rules (complex tier only) */}
          {isComplex && (
            <div className="mb-4 bg-asphalt/30 border border-steel/10 p-3">
              <button
                type="button"
                onClick={() => setShowDefaultRules(!showDefaultRules)}
                className="flex items-center gap-2 text-steel font-telemetry text-xs tracking-wider uppercase hover:text-chalk transition-colors"
              >
                {showDefaultRules ? '\u25BC' : '\u25B6'} Default Driver Rules
              </button>
              {showDefaultRules && (<>
                <div className="mt-3">
                  <p className="text-steel/60 font-body text-xs mb-3">
                    These defaults apply to drivers without individual overrides.
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
                    <div>
                      <label className={labelCls}>Min Stint</label>
                      <DurationMmSs id={`${fieldId}-def-min-stint`} value={defaultMinStint} onChange={setDefaultMinStint} label="Default min stint" />
                    </div>
                    <div>
                      <label className={labelCls}>Max Stint</label>
                      <DurationMmSs id={`${fieldId}-def-max-stint`} value={defaultMaxStint} onChange={setDefaultMaxStint} label="Default max stint" />
                    </div>
                    <div>
                      <label className={labelCls}>Min Total</label>
                      <DurationMmSs id={`${fieldId}-def-min-total`} value={defaultMinTotal} onChange={setDefaultMinTotal} label="Default min total" />
                    </div>
                    <div>
                      <label className={labelCls}>Max Total</label>
                      <DurationMmSs id={`${fieldId}-def-max-total`} value={defaultMaxTotal} onChange={setDefaultMaxTotal} label="Default max total" />
                    </div>
                    <div>
                      <label className={labelCls}>Min Rest</label>
                      <DurationMmSs id={`${fieldId}-def-min-rest`} value={defaultMinRest} onChange={setDefaultMinRest} label="Default min rest" />
                    </div>
                    <div className="flex items-end pb-2">
                      <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                        <input type="checkbox" checked={defaultAllowDouble} onChange={(e) => setDefaultAllowDouble(e.target.checked)} className="accent-pit-orange" />
                        Allow double stint
                      </label>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setDrivers(drivers.map(d => ({
                      ...d,
                      min_stint_s: defaultMinStint || d.min_stint_s,
                      max_stint_s: defaultMaxStint || d.max_stint_s,
                      min_cumulative_s: defaultMinTotal || d.min_cumulative_s,
                      max_cumulative_s: defaultMaxTotal || d.max_cumulative_s,
                      min_rest_s: defaultMinRest || d.min_rest_s,
                      allow_double_stint: defaultAllowDouble,
                    })));
                  }}
                  className="mt-3 px-3 py-1.5 text-xs font-telemetry text-gold border border-gold/40 rounded hover:bg-gold/10 transition-colors"
                >
                  Apply to all drivers
                </button>
              </>)}
            </div>
          )}

          <div className="space-y-3">
            {drivers.map((d, i) => (
              <div key={i} className="bg-asphalt/40 border border-steel/10 p-3">
                {/* Row 1: identity */}
                <div className="flex items-center gap-3 mb-2">
                  <input type="color" aria-label={`Driver ${i + 1} color`} value={d.color_hex} onChange={(e) => updateDriver(i, 'color_hex', e.target.value)} className="w-8 h-8 rounded cursor-pointer bg-transparent border-0 shrink-0" />
                  <input aria-label={`Driver ${i + 1} name`} className={`${inputCls} flex-1 min-w-[10rem]`} value={d.driver_name} onChange={(e) => updateDriver(i, 'driver_name', e.target.value)} placeholder="Driver name" />
                  <input aria-label={`Driver ${i + 1} weight (kg)`} className={`${inputCls} w-20`} value={d.weight_kg} onChange={(e) => updateDriver(i, 'weight_kg', e.target.value)} placeholder="kg" type="number" step="0.1" />
                  <button type="button" aria-label={`Toggle driver ${i + 1} constraints`} onClick={() => updateDriver(i, 'showConstraints', !d.showConstraints)} className="text-steel hover:text-chalk text-xs font-telemetry transition-colors shrink-0">
                    {d.showConstraints ? '\u25BC' : '\u25B6'} Rules
                  </button>
                  {drivers.length > 1 && (
                    <button type="button" onClick={() => removeDriver(i)} aria-label={`Remove driver ${i + 1}`} className="text-safety-red hover:text-safety-red/80 text-sm transition-colors">{'\u2715'}</button>
                  )}
                </div>
                {/* Row 2: performance fields */}
                <div className="grid grid-cols-3 gap-3 pl-11 mb-2">
                  <div>
                    <label className={labelCls}>COM Channel</label>
                    <input aria-label={`Driver ${i + 1} COM channel`} className={inputCls} value={d.com_channel} onChange={(e) => updateDriver(i, 'com_channel', e.target.value)} placeholder="e.g. CH3" />
                  </div>
                  <div>
                    <label className={labelCls}>Avg Lap Time (s)</label>
                    <input aria-label={`Driver ${i + 1} avg lap time`} className={inputCls} value={d.avg_lap_time_s} onChange={(e) => updateDriver(i, 'avg_lap_time_s', e.target.value)} placeholder="e.g. 62.5" type="number" step="0.1" />
                  </div>
                  {/* Rain Pace hidden until V2 */}
                </div>
                {d.showConstraints && (
                  <>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 mt-2 pl-11">
                      <div><label htmlFor={`${fieldId}-d${i}-min-stint`} className={labelCls}>Min Stint</label><DurationMmSs id={`${fieldId}-d${i}-min-stint`} value={d.min_stint_s} onChange={(v) => updateDriver(i, 'min_stint_s', v)} label="Min stint" /></div>
                      <div><label htmlFor={`${fieldId}-d${i}-max-stint`} className={labelCls}>Max Stint</label><DurationMmSs id={`${fieldId}-d${i}-max-stint`} value={d.max_stint_s} onChange={(v) => updateDriver(i, 'max_stint_s', v)} label="Max stint" /></div>
                      <div><label htmlFor={`${fieldId}-d${i}-min-total`} className={labelCls}>Min Total</label><DurationMmSs id={`${fieldId}-d${i}-min-total`} value={d.min_cumulative_s} onChange={(v) => updateDriver(i, 'min_cumulative_s', v)} label="Min total" /></div>
                      <div><label htmlFor={`${fieldId}-d${i}-max-total`} className={labelCls}>Max Total</label><DurationMmSs id={`${fieldId}-d${i}-max-total`} value={d.max_cumulative_s} onChange={(v) => updateDriver(i, 'max_cumulative_s', v)} label="Max total" /></div>
                      <div><label htmlFor={`${fieldId}-d${i}-min-rest`} className={labelCls}>Min Rest</label><DurationMmSs id={`${fieldId}-d${i}-min-rest`} value={d.min_rest_s} onChange={(v) => updateDriver(i, 'min_rest_s', v)} label="Min rest" /></div>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 mt-2 pl-11">
                      <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer col-span-1">
                        <input type="checkbox" checked={d.allow_double_stint} onChange={(e) => updateDriver(i, 'allow_double_stint', e.target.checked)} className="accent-pit-orange" />
                        Allow double stint
                      </label>
                    </div>
                  </>
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
          </div>
          <div className="flex flex-wrap gap-6 mt-4">
            <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
              <input type="checkbox" checked={mandatoryChange} onChange={(e) => setMandatoryChange(e.target.checked)} className="accent-pit-orange" />
              Mandatory driver change
            </label>
            {!quickChange && (
              <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                <input type="checkbox" checked={refuelingAllowed} onChange={(e) => setRefuelingAllowed(e.target.checked)} className="accent-pit-orange" />
                Refueling allowed
              </label>
            )}
            <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
              <input type="checkbox" checked={quickChange} onChange={(e) => setQuickChange(e.target.checked)} className="accent-pit-orange" />
              Quick change (Sport category)
            </label>
          </div>

          {/* Optimization Mode (complex tier only) */}
          {isComplex && (
            <div className="mt-4">
              <label className={labelCls}>Optimization Mode</label>
              <div className="flex gap-2 mt-1">
                <button
                  type="button"
                  onClick={() => setOptimizationMode('equal')}
                  className={`px-4 py-2 text-sm font-telemetry tracking-wider uppercase border transition-colors ${
                    optimizationMode === 'equal'
                      ? 'bg-pit-orange text-white border-pit-orange'
                      : 'border-steel/30 text-steel hover:text-chalk hover:border-chalk/30'
                  }`}
                >
                  Equal Time
                </button>
                <button
                  type="button"
                  onClick={() => setOptimizationMode('performance')}
                  className={`px-4 py-2 text-sm font-telemetry tracking-wider uppercase border transition-colors ${
                    optimizationMode === 'performance'
                      ? 'bg-pit-orange text-white border-pit-orange'
                      : 'border-steel/30 text-steel hover:text-chalk hover:border-chalk/30'
                  }`}
                >
                  Performance
                </button>
              </div>
            </div>
          )}

          {/* Blackout Windows */}
          <div className="grid grid-cols-2 gap-4 mt-4">
            <div>
              <label htmlFor={`${fieldId}-blackout-start`} className={labelCls}>No pit first (min)</label>
              <input id={`${fieldId}-blackout-start`} type="number" className={inputCls} value={blackoutStart} onChange={(e) => setBlackoutStart(e.target.value)} min="0" placeholder="e.g. 10" />
            </div>
            <div>
              <label htmlFor={`${fieldId}-blackout-end`} className={labelCls}>No pit last (min)</label>
              <input id={`${fieldId}-blackout-end`} type="number" className={inputCls} value={blackoutEnd} onChange={(e) => setBlackoutEnd(e.target.value)} min="0" placeholder="e.g. 5" />
            </div>
          </div>
        </div>

        {/* Tech Stop (complex tier only) */}
        {isComplex && (
          <div className={sectionCls}>
            <h2 className="font-monument text-lg text-chalk mb-4">Tech Stop</h2>
            <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer mb-4">
              <input type="checkbox" checked={techStopEnabled} onChange={(e) => setTechStopEnabled(e.target.checked)} className="accent-pit-orange" />
              Enable mandatory tech stop
            </label>
            {techStopEnabled && (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div>
                  <label htmlFor={`${fieldId}-tech-dur`} className={labelCls}>Duration (mm:ss)</label>
                  <DurationMmSs id={`${fieldId}-tech-dur`} value={techStopDuration} onChange={setTechStopDuration} label="Tech stop duration" />
                </div>
                <div>
                  <label className={labelCls}>Window Start (hh:mm)</label>
                  <div className="flex items-center gap-1">
                    <input
                      id={`${fieldId}-tech-win-start`}
                      type="number"
                      aria-label="Window start hours"
                      className={`${inputCls} w-14 text-center`}
                      value={techStopWindowStart ? String(Math.floor(parseInt(techStopWindowStart) / 3600)) : ''}
                      onChange={(e) => {
                        const hh = parseInt(e.target.value) || 0;
                        const oldMm = techStopWindowStart ? Math.floor((parseInt(techStopWindowStart) % 3600) / 60) : 0;
                        setTechStopWindowStart(String(hh * 3600 + oldMm * 60));
                      }}
                      min="0" placeholder="h"
                    />
                    <span className="text-steel">:</span>
                    <input
                      type="number"
                      aria-label="Window start minutes"
                      className={`${inputCls} w-14 text-center`}
                      value={techStopWindowStart ? String(Math.floor((parseInt(techStopWindowStart) % 3600) / 60)) : ''}
                      onChange={(e) => {
                        const mm = parseInt(e.target.value) || 0;
                        const oldHh = techStopWindowStart ? Math.floor(parseInt(techStopWindowStart) / 3600) : 0;
                        setTechStopWindowStart(String(oldHh * 3600 + mm * 60));
                      }}
                      min="0" max="59" placeholder="m"
                    />
                  </div>
                </div>
                <div>
                  <label className={labelCls}>Window End (hh:mm)</label>
                  <div className="flex items-center gap-1">
                    <input
                      id={`${fieldId}-tech-win-end`}
                      type="number"
                      aria-label="Window end hours"
                      className={`${inputCls} w-14 text-center`}
                      value={techStopWindowEnd ? String(Math.floor(parseInt(techStopWindowEnd) / 3600)) : ''}
                      onChange={(e) => {
                        const hh = parseInt(e.target.value) || 0;
                        const oldMm = techStopWindowEnd ? Math.floor((parseInt(techStopWindowEnd) % 3600) / 60) : 0;
                        setTechStopWindowEnd(String(hh * 3600 + oldMm * 60));
                      }}
                      min="0" placeholder="h"
                    />
                    <span className="text-steel">:</span>
                    <input
                      type="number"
                      aria-label="Window end minutes"
                      className={`${inputCls} w-14 text-center`}
                      value={techStopWindowEnd ? String(Math.floor((parseInt(techStopWindowEnd) % 3600) / 60)) : ''}
                      onChange={(e) => {
                        const mm = parseInt(e.target.value) || 0;
                        const oldHh = techStopWindowEnd ? Math.floor(parseInt(techStopWindowEnd) / 3600) : 0;
                        setTechStopWindowEnd(String(oldHh * 3600 + mm * 60));
                      }}
                      min="0" max="59" placeholder="m"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Weather Forecast (complex tier only) */}
        {isComplex && (
          <div className={sectionCls}>
            <div className="flex items-center justify-between mb-2">
              <div>
                <h2 className="font-monument text-lg text-chalk">Weather Forecast</h2>
                <p className="text-steel font-body text-xs mt-1">
                  Add expected rain or damp windows. The optimizer will cluster pit stops during rain (cheaper in laps) and assign rain-specialist drivers to wet stints.
                </p>
              </div>
              <button type="button" onClick={() => setWeatherWindows([...weatherWindows, { startH: '', startM: '0', endH: '', endM: '0', condition: 'wet', confidence: '70' }])} className="px-3 py-1 text-sm font-telemetry text-marshal-yellow border border-marshal-yellow/40 hover:bg-marshal-yellow/10 transition-colors shrink-0">
                + Add Window
              </button>
            </div>
            {weatherWindows.length === 0 ? (
              <p className="text-steel font-body text-sm mt-3">No weather windows added. The optimizer assumes dry conditions for the entire race.</p>
            ) : (<>
              <div className="space-y-3 mt-3">
                {weatherWindows.map((w, i) => (
                  <div key={i} className="grid grid-cols-[1fr_auto_1fr_1fr_1fr_auto] items-center gap-3 bg-asphalt/40 border border-steel/10 p-3">
                    <div>
                      {i === 0 && <label className={`${labelCls} mb-1`}>Start (h:m)</label>}
                      <div className="flex items-center gap-1">
                        <input type="number" className={`${inputCls} flex-1 text-center`} value={w.startH} onChange={(e) => { const nw = [...weatherWindows]; nw[i] = {...nw[i], startH: e.target.value}; setWeatherWindows(nw); }} min="0" placeholder="h" />
                        <span className="text-steel">:</span>
                        <input type="number" className={`${inputCls} flex-1 text-center`} value={w.startM} onChange={(e) => { const nw = [...weatherWindows]; nw[i] = {...nw[i], startM: e.target.value}; setWeatherWindows(nw); }} min="0" max="59" placeholder="m" />
                      </div>
                    </div>
                    <span className="text-steel pt-4">{'\u2192'}</span>
                    <div>
                      {i === 0 && <label className={`${labelCls} mb-1`}>End (h:m)</label>}
                      <div className="flex items-center gap-1">
                        <input type="number" className={`${inputCls} flex-1 text-center`} value={w.endH} onChange={(e) => { const nw = [...weatherWindows]; nw[i] = {...nw[i], endH: e.target.value}; setWeatherWindows(nw); }} min="0" placeholder="h" />
                        <span className="text-steel">:</span>
                        <input type="number" className={`${inputCls} flex-1 text-center`} value={w.endM} onChange={(e) => { const nw = [...weatherWindows]; nw[i] = {...nw[i], endM: e.target.value}; setWeatherWindows(nw); }} min="0" max="59" placeholder="m" />
                      </div>
                    </div>
                    <div>
                      {i === 0 && <label className={`${labelCls} mb-1`}>Condition</label>}
                      <select className={`${inputCls} w-full`} value={w.condition} onChange={(e) => { const nw = [...weatherWindows]; nw[i] = {...nw[i], condition: e.target.value}; setWeatherWindows(nw); }}>
                        <option value="dry">Dry</option>
                        <option value="damp">Damp</option>
                        <option value="wet">Wet</option>
                      </select>
                    </div>
                    <div>
                      {i === 0 && <label className={`${labelCls} mb-1`}>Likelihood</label>}
                      <div className="flex items-center gap-1">
                        <input type="number" className={`${inputCls} flex-1 text-center`} value={w.confidence} onChange={(e) => { const nw = [...weatherWindows]; nw[i] = {...nw[i], confidence: e.target.value}; setWeatherWindows(nw); }} min="0" max="100" step="5" placeholder="%" />
                        <span className="text-steel text-xs">%</span>
                      </div>
                    </div>
                    <button type="button" onClick={() => setWeatherWindows(weatherWindows.filter((_, j) => j !== i))} className="text-safety-red hover:text-safety-red/80 text-sm transition-colors pt-4">{'\u2715'}</button>
                  </div>
                ))}
              </div>
            </>)}
          </div>
        )}

        {/* Sleep Windows (endurance races + complex tier) */}
        {isEndurance && isComplex && (
          <div className={sectionCls}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-monument text-lg text-chalk">Sleep Windows</h2>
                <p className="text-steel font-body text-sm mt-1">
                  Plan driver rest periods. The optimizer will avoid scheduling stints during sleep windows when possible.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSleepWindows([...sleepWindows, { driver_index: '', start_hh: '', start_mm: '00', end_hh: '', end_mm: '00', label: '' }])}
                className="px-3 py-1 text-sm font-telemetry text-pit-orange border border-pit-orange/40 hover:bg-pit-orange/10 transition-colors"
              >
                + Add Sleep Window
              </button>
            </div>
            {sleepWindows.length === 0 ? (
              <p className="text-steel font-body text-sm">No sleep windows configured.</p>
            ) : (
              <div className="space-y-3">
                {sleepWindows.map((sw, i) => (
                  <div key={i} className="flex flex-wrap items-end gap-3 bg-asphalt/40 border border-steel/10 p-3">
                    {/* Driver select */}
                    <div className="flex-1 min-w-[140px]">
                      {i === 0 && <label className={labelCls}>Driver</label>}
                      <select
                        aria-label={`Sleep window ${i + 1} driver`}
                        value={sw.driver_index}
                        onChange={e => updateSleepWindow(i, 'driver_index', e.target.value)}
                        className={`${inputCls} w-full`}
                      >
                        <option value="">Select driver...</option>
                        {drivers.map((d, di) => (
                          <option key={di} value={String(di)}>{d.driver_name || `Driver ${di + 1}`}</option>
                        ))}
                      </select>
                    </div>

                    {/* Start time */}
                    <div>
                      {i === 0 && <label className={labelCls}>Start</label>}
                      <div className="flex items-center gap-1">
                        <input type="number" min="0" max="47" placeholder="h"
                          aria-label={`Sleep window ${i + 1} start hours`}
                          value={sw.start_hh}
                          onChange={e => updateSleepWindow(i, 'start_hh', e.target.value)}
                          className={`${inputCls} w-14 text-center`}
                        />
                        <span className="text-steel">:</span>
                        <input type="number" min="0" max="59" placeholder="m"
                          aria-label={`Sleep window ${i + 1} start minutes`}
                          value={sw.start_mm}
                          onChange={e => updateSleepWindow(i, 'start_mm', e.target.value)}
                          className={`${inputCls} w-14 text-center`}
                        />
                      </div>
                    </div>

                    <span className="text-steel pb-2">{'\u2192'}</span>

                    {/* End time */}
                    <div>
                      {i === 0 && <label className={labelCls}>End</label>}
                      <div className="flex items-center gap-1">
                        <input type="number" min="0" max="47" placeholder="h"
                          aria-label={`Sleep window ${i + 1} end hours`}
                          value={sw.end_hh}
                          onChange={e => updateSleepWindow(i, 'end_hh', e.target.value)}
                          className={`${inputCls} w-14 text-center`}
                        />
                        <span className="text-steel">:</span>
                        <input type="number" min="0" max="59" placeholder="m"
                          aria-label={`Sleep window ${i + 1} end minutes`}
                          value={sw.end_mm}
                          onChange={e => updateSleepWindow(i, 'end_mm', e.target.value)}
                          className={`${inputCls} w-14 text-center`}
                        />
                      </div>
                    </div>

                    {/* Label */}
                    <div className="flex-1 min-w-[100px]">
                      {i === 0 && <label className={labelCls}>Label</label>}
                      <input type="text" placeholder="e.g. Night rest"
                        aria-label={`Sleep window ${i + 1} label`}
                        value={sw.label}
                        onChange={e => updateSleepWindow(i, 'label', e.target.value)}
                        className={inputCls}
                      />
                    </div>

                    {/* Remove button */}
                    <button type="button" onClick={() => setSleepWindows(sleepWindows.filter((_, j) => j !== i))}
                      aria-label={`Remove sleep window ${i + 1}`}
                      className="text-safety-red hover:text-safety-red/80 text-sm transition-colors">{'\u2715'}</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Fuel & Weight (complex tier only) */}
        {isComplex && (
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
              <div>
                <label htmlFor={`${fieldId}-min-total-kg`} className={labelCls}>Min Kart+Driver (kg)</label>
                <input id={`${fieldId}-min-total-kg`} type="number" className={inputCls} value={minTotal} onChange={(e) => setMinTotal(e.target.value)} step="0.1" placeholder="e.g. 170" />
                <span className="text-steel/40 font-body text-[10px] mt-0.5 block">Regulation minimum on the scales</span>
              </div>
              <div className="flex items-end pb-2">
                <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                  <input type="checkbox" checked={weighOnExit} onChange={(e) => setWeighOnExit(e.target.checked)} className="accent-pit-orange" />
                  Weigh on pit exit
                </label>
              </div>
            </div>
          </div>
        )}

        {/* Qualifying (complex tier only) */}
        {isComplex && (
          <div className={sectionCls}>
            <button type="button" aria-label="Toggle qualifying section" onClick={() => setShowQuali(!showQuali)} className="flex items-center gap-2 font-monument text-lg text-chalk">
              {showQuali ? '\u25BC' : '\u25B6'} Qualifying
            </button>
            {showQuali && (
              <div className="grid grid-cols-2 gap-4 mt-4">
                <div><label htmlFor={`${fieldId}-quali-dur`} className={labelCls}>Duration</label><DurationMmSs id={`${fieldId}-quali-dur`} value={qualiDuration} onChange={setQualiDuration} label="Qualifying duration" /></div>
                <div className="flex items-end pb-2">
                  <label className="flex items-center gap-2 text-steel font-body text-sm cursor-pointer">
                    <input type="checkbox" checked={refuelAfterQuali} onChange={(e) => setRefuelAfterQuali(e.target.checked)} className="accent-pit-orange" />
                    Refuel after qualifying
                  </label>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Submit */}
        <div className="flex items-center gap-4 mt-6">
          <button
            type="submit"
            disabled={isSubmitting}
            className="px-6 py-3 bg-pit-orange text-white font-telemetry text-sm tracking-wider uppercase hover:bg-pit-orange/80 transition-colors disabled:opacity-50"
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
