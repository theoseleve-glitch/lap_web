'use client';

import { useState, useCallback, useMemo } from 'react';
import { DRIVER_COLORS, CONDITIONS } from './types';

interface DetectedLap {
  lap_number: number;
  lap_time_s: number;
  status: 'valid' | 'pit' | 'anomaly';
}

interface DetectedStint {
  stint_number: number;
  start_lap: number;
  end_lap: number;
  lap_count: number;
  pit_lap_number: number | null;
  pit_lap_time_s: number | null;
}

interface StintConfig {
  stint_number: number;
  start_lap: number;
  end_lap: number;
  valid_laps: number[];
  driver_name: string;
  condition: string;
}

interface StintConfigFlowProps {
  laps: DetectedLap[];
  autoStints: DetectedStint[];
  drivers: string[];
  medianLapTime: number;
  pitThreshold: number;
  onProcess: (stints: StintConfig[]) => void;
  isProcessing: boolean;
}

function formatTime(s: number | null): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export function StintConfigFlow({
  laps,
  autoStints,
  drivers,
  medianLapTime,
  pitThreshold,
  onProcess,
  isProcessing,
}: StintConfigFlowProps) {
  // Lap overrides: user can change status
  const [lapOverrides, setLapOverrides] = useState<Record<number, string>>({});
  // Per-stint config
  const [stintDrivers, setStintDrivers] = useState<Record<number, string>>({});
  const [stintConditions, setStintConditions] = useState<Record<number, string>>({});

  // Compute effective lap statuses (auto + overrides)
  const effectiveLaps = useMemo(() => {
    return laps.map((l) => ({
      ...l,
      status: (lapOverrides[l.lap_number] || l.status) as 'valid' | 'pit' | 'anomaly' | 'ignore',
    }));
  }, [laps, lapOverrides]);

  // Rebuild stints from effective statuses
  const stints = useMemo(() => {
    const result: DetectedStint[] = [];
    let current: number[] = [];

    for (const lap of effectiveLaps) {
      if (lap.status === 'pit' || lap.status === 'ignore') {
        if (current.length > 0) {
          result.push({
            stint_number: result.length + 1,
            start_lap: current[0],
            end_lap: current[current.length - 1],
            lap_count: current.length,
            pit_lap_number: lap.status === 'pit' ? lap.lap_number : null,
            pit_lap_time_s: lap.status === 'pit' ? lap.lap_time_s : null,
          });
          current = [];
        }
      } else {
        current.push(lap.lap_number);
      }
    }
    if (current.length > 0) {
      result.push({
        stint_number: result.length + 1,
        start_lap: current[0],
        end_lap: current[current.length - 1],
        lap_count: current.length,
        pit_lap_number: null,
        pit_lap_time_s: null,
      });
    }
    return result;
  }, [effectiveLaps]);

  const allAssigned = stints.every((s) => stintDrivers[s.stint_number]);

  const handleProcess = useCallback(() => {
    // Build explicit list of valid laps per stint
    // Must match the same grouping logic used by the `stints` useMemo
    const stintValidLaps: Record<number, number[]> = {};
    let currentValid: number[] = [];
    let stintCount = 0;
    for (const lap of effectiveLaps) {
      if (lap.status === 'pit' || lap.status === 'ignore') {
        if (currentValid.length > 0) {
          stintCount++;
          stintValidLaps[stintCount] = [...currentValid];
          currentValid = [];
        }
      } else if (lap.status === 'valid') {
        currentValid.push(lap.lap_number);
      }
    }
    if (currentValid.length > 0) {
      stintCount++;
      stintValidLaps[stintCount] = [...currentValid];
    }

    const configs: StintConfig[] = stints.map((s) => ({
      stint_number: s.stint_number,
      start_lap: s.start_lap,
      end_lap: s.end_lap,
      lap_count: s.lap_count,
      valid_laps: stintValidLaps[s.stint_number] || [],
      pit_lap_number: s.pit_lap_number,
      pit_lap_time_s: s.pit_lap_time_s,
      pit_duration_s: (s as any).pit_duration_s ?? null,
      driver_name: stintDrivers[s.stint_number] || drivers[0] || 'Unknown',
      condition: stintConditions[s.stint_number] || 'dry',
    }));
    onProcess(configs);
  }, [stints, stintDrivers, stintConditions, drivers, onProcess, effectiveLaps]);

  const statusColors: Record<string, string> = {
    valid: 'text-acid-green',
    pit: 'text-pit-orange',
    anomaly: 'text-marshal-yellow',
    ignore: 'text-steel/30',
  };

  return (
    <div className="space-y-6">
      {/* Lap Table */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-1">Lap Classification</h3>
        <p className="text-steel text-xs font-body mb-4">
          {effectiveLaps.length} laps detected &middot; Median: {formatTime(medianLapTime)} &middot; Pit threshold: {pitThreshold}s
        </p>
        <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
          <table className="w-full text-xs font-body">
            <thead className="sticky top-0 bg-concrete">
              <tr className="text-steel border-b border-steel/10">
                <th className="py-2 text-left">Lap</th>
                <th className="py-2 text-right">Time</th>
                <th className="py-2 text-left">Status</th>
                <th className="py-2 text-left">Override</th>
              </tr>
            </thead>
            <tbody>
              {effectiveLaps.map((lap) => (
                <tr key={lap.lap_number} className={`border-b border-steel/5 ${statusColors[lap.status]}`}>
                  <td className="py-1.5 font-telemetry">{lap.lap_number}</td>
                  <td className="py-1.5 text-right font-telemetry">{formatTime(lap.lap_time_s)}</td>
                  <td className="py-1.5">
                    <span className={`text-[10px] font-telemetry uppercase ${statusColors[lap.status]}`}>
                      {lap.status}
                    </span>
                  </td>
                  <td className="py-1.5">
                    <select
                      value={lapOverrides[lap.lap_number] || ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        setLapOverrides((prev) => {
                          const next = { ...prev };
                          if (val) next[lap.lap_number] = val;
                          else delete next[lap.lap_number];
                          return next;
                        });
                      }}
                      className="bg-asphalt border border-steel/20 rounded px-1.5 py-0.5 text-chalk text-[10px]"
                    >
                      <option value="">Auto</option>
                      <option value="valid">Valid</option>
                      <option value="pit">Pit Stop</option>
                      <option value="ignore">Ignore</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Stint Assignment */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-1">Stint Assignment</h3>
        <p className="text-steel text-xs font-body mb-4">
          {stints.length} stints detected. Assign a driver and condition to each.
        </p>
        <div className="space-y-2">
          {stints.map((stint, idx) => (
            <div key={stint.stint_number} className="flex items-center gap-3 bg-asphalt/50 rounded-lg px-4 py-3 border border-steel/10">
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: stintDrivers[stint.stint_number] ? DRIVER_COLORS[drivers.indexOf(stintDrivers[stint.stint_number]) % DRIVER_COLORS.length] : '#555' }}
              />
              <span className="font-telemetry text-chalk text-sm w-16">S{stint.stint_number}</span>
              <span className="text-steel text-xs font-body w-28">L{stint.start_lap}–{stint.end_lap} ({stint.lap_count})</span>
              <select
                value={stintDrivers[stint.stint_number] || ''}
                onChange={(e) => setStintDrivers((prev) => ({ ...prev, [stint.stint_number]: e.target.value }))}
                className="bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-xs flex-1 max-w-[180px]"
              >
                <option value="">Select driver</option>
                {drivers.map((d) => (<option key={d} value={d}>{d}</option>))}
              </select>
              <select
                value={stintConditions[stint.stint_number] || 'dry'}
                onChange={(e) => setStintConditions((prev) => ({ ...prev, [stint.stint_number]: e.target.value }))}
                className="bg-asphalt border border-steel/20 rounded px-2 py-1 text-chalk text-xs w-20"
              >
                {CONDITIONS.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
              {stint.pit_lap_time_s && (
                <span className="text-pit-orange text-[10px] font-telemetry">pit: {stint.pit_lap_time_s.toFixed(0)}s</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Process Button */}
      <button
        type="button"
        onClick={handleProcess}
        disabled={!allAssigned || isProcessing || stints.length === 0}
        className="w-full py-3 bg-gold text-carbon font-telemetry text-sm font-semibold rounded-lg hover:bg-gold/90 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
      >
        {isProcessing ? 'Processing...' : `Process ${stints.length} Stints`}
      </button>
    </div>
  );
}
