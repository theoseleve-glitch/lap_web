'use client';

import { useState, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import type { Stint, StintAssignment, StintsResponse, CONDITIONS } from './types';
import { DRIVER_COLORS } from './types';

interface SetupFlowProps {
  sessionId: string;
  stints: Stint[];
  pitThreshold: number;
  onComplete: () => void;
}

function formatTime(s: number | null | undefined): string {
  if (s == null) return '--';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

export function SetupFlow({ sessionId, stints, pitThreshold, onComplete }: SetupFlowProps) {
  const queryClient = useQueryClient();
  const [threshold, setThreshold] = useState(pitThreshold);
  const [drivers, setDrivers] = useState<string[]>([]);
  const [newDriverName, setNewDriverName] = useState('');
  const [assignments, setAssignments] = useState<Record<number, string>>({});
  const [conditions, setConditions] = useState<Record<number, string>>({});

  const reconfigureMutation = useMutation({
    mutationFn: (newThreshold: number) =>
      api.post<StintsResponse>(`/sessions/${sessionId}/stints/configure`, { pit_threshold_s: newThreshold }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stints', sessionId] });
    },
  });

  const assignMutation = useMutation({
    mutationFn: (data: StintAssignment[]) =>
      api.post(`/sessions/${sessionId}/stints/assign`, { assignments: data }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['endurance-report', sessionId] });
      onComplete();
    },
  });

  const addDriver = useCallback(() => {
    const name = newDriverName.trim();
    if (name && !drivers.includes(name)) {
      setDrivers((prev) => [...prev, name]);
      setNewDriverName('');
    }
  }, [newDriverName, drivers]);

  const removeDriver = useCallback((name: string) => {
    setDrivers((prev) => prev.filter((d) => d !== name));
    setAssignments((prev) => {
      const next = { ...prev };
      for (const [k, v] of Object.entries(next)) {
        if (v === name) delete next[Number(k)];
      }
      return next;
    });
  }, []);

  const toggleStintAssignment = useCallback((stintNum: number, driverName: string) => {
    setAssignments((prev) => {
      const next = { ...prev };
      if (next[stintNum] === driverName) {
        delete next[stintNum];
      } else {
        next[stintNum] = driverName;
      }
      return next;
    });
  }, []);

  const handleGenerateReport = useCallback(() => {
    const data: StintAssignment[] = Object.entries(assignments).map(([stintNum, driverName]) => ({
      stint_number: Number(stintNum),
      driver_name: driverName,
      condition: conditions[Number(stintNum)] || 'dry',
    }));
    assignMutation.mutate(data);
  }, [assignments, conditions, assignMutation]);

  const allStintsAssigned = stints.every((s) => assignments[s.stint_number]);

  return (
    <div className="space-y-6">
      {/* Stint Detection Summary */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-1">Stint Detection</h3>
        <p className="text-steel text-xs font-body mb-4">
          Detected <strong className="text-chalk">{stints.length} stints</strong> using a {threshold}s pit threshold
        </p>

        <div className="flex items-center gap-3 mb-4">
          <label className="text-steel text-xs font-body">Pit threshold (s):</label>
          <input
            type="number"
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-24 px-2 py-1 bg-asphalt border border-steel/20 rounded text-chalk text-sm font-telemetry"
            min={10}
            max={600}
          />
          <button
            type="button"
            onClick={() => reconfigureMutation.mutate(threshold)}
            disabled={reconfigureMutation.isPending}
            className="px-3 py-1 text-xs font-body bg-steel/10 border border-steel/20 rounded text-chalk hover:bg-steel/20 transition-colors disabled:opacity-50"
          >
            {reconfigureMutation.isPending ? 'Detecting...' : 'Re-detect'}
          </button>
        </div>

        {/* Stint table */}
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-body">
            <thead>
              <tr className="text-steel border-b border-steel/10">
                <th className="py-2 text-left">Stint</th>
                <th className="py-2 text-left">Laps</th>
                <th className="py-2 text-right">Best</th>
                <th className="py-2 text-right">Mean</th>
                <th className="py-2 text-right">Pit Time</th>
                <th className="py-2 text-left">Condition</th>
              </tr>
            </thead>
            <tbody>
              {stints.map((s) => (
                <tr key={s.stint_number} className="border-b border-steel/5 text-chalk">
                  <td className="py-2 font-telemetry">{s.stint_number}</td>
                  <td className="py-2">{s.start_lap}–{s.end_lap} ({s.lap_count})</td>
                  <td className="py-2 text-right font-telemetry text-acid-green">{formatTime(s.best_lap_s)}</td>
                  <td className="py-2 text-right font-telemetry">{formatTime(s.mean_lap_s)}</td>
                  <td className="py-2 text-right font-telemetry text-pit-orange">{s.pit_lap_time_s ? `${s.pit_lap_time_s.toFixed(1)}s` : '—'}</td>
                  <td className="py-2">
                    <select
                      value={conditions[s.stint_number] || 'dry'}
                      onChange={(e) => setConditions((prev) => ({ ...prev, [s.stint_number]: e.target.value }))}
                      className="bg-asphalt border border-steel/20 rounded px-2 py-0.5 text-chalk text-xs"
                    >
                      <option value="dry">Dry</option>
                      <option value="damp">Damp</option>
                      <option value="wet">Wet</option>
                      <option value="mixed">Mixed</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Driver Assignment */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-6">
        <h3 className="text-lg font-monument text-chalk mb-1">Driver Assignment</h3>
        <p className="text-steel text-xs font-body mb-4">Add drivers and assign them to stints</p>

        {/* Add driver */}
        <div className="flex items-center gap-2 mb-4">
          <input
            type="text"
            value={newDriverName}
            onChange={(e) => setNewDriverName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addDriver()}
            placeholder="Driver name"
            className="flex-1 max-w-xs px-3 py-2 bg-asphalt border border-steel/20 rounded-lg text-chalk text-sm font-body placeholder:text-steel/40"
          />
          <button
            type="button"
            onClick={addDriver}
            className="px-4 py-2 bg-acid-green/10 border border-acid-green/30 rounded-lg text-acid-green text-sm font-body hover:bg-acid-green/20 transition-colors"
          >
            + Add Driver
          </button>
        </div>

        {/* Driver cards with stint checkboxes */}
        {drivers.length > 0 && (
          <div className="space-y-3">
            {drivers.map((driver, idx) => (
              <div key={driver} className="bg-asphalt/50 rounded-lg border border-steel/10 p-4">
                <div className="flex items-center gap-3 mb-3">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: DRIVER_COLORS[idx % DRIVER_COLORS.length] }}
                  />
                  <span className="text-chalk font-body text-sm font-medium">{driver}</span>
                  <button
                    type="button"
                    onClick={() => removeDriver(driver)}
                    className="ml-auto text-steel/40 hover:text-safety-red text-xs transition-colors"
                  >
                    Remove
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {stints.map((s) => {
                    const assigned = assignments[s.stint_number] === driver;
                    const takenByOther = assignments[s.stint_number] && assignments[s.stint_number] !== driver;
                    return (
                      <button
                        key={s.stint_number}
                        type="button"
                        onClick={() => toggleStintAssignment(s.stint_number, driver)}
                        disabled={!!takenByOther}
                        className={`px-3 py-1.5 rounded text-xs font-telemetry transition-colors ${
                          assigned
                            ? 'bg-acid-green/20 border border-acid-green/40 text-acid-green'
                            : takenByOther
                              ? 'bg-steel/5 border border-steel/10 text-steel/30 cursor-not-allowed'
                              : 'bg-steel/10 border border-steel/20 text-steel hover:text-chalk hover:border-steel/40'
                        }`}
                      >
                        S{s.stint_number} (L{s.start_lap}–{s.end_lap})
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Generate Report */}
      <button
        type="button"
        onClick={handleGenerateReport}
        disabled={!allStintsAssigned || drivers.length < 1 || assignMutation.isPending}
        className="w-full py-3 bg-gold text-carbon font-telemetry text-sm font-semibold rounded-lg hover:bg-gold/90 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
      >
        {assignMutation.isPending ? 'Generating Report...' : `Generate Endurance Report (${Object.keys(assignments).length}/${stints.length} stints assigned)`}
      </button>

      {!allStintsAssigned && drivers.length > 0 && (
        <p className="text-steel text-xs font-body text-center">
          Assign all {stints.length} stints to a driver to generate the report
        </p>
      )}
    </div>
  );
}
