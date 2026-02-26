'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, FormField } from '@/components/app';

interface Driver {
  driver_id: number;
  driver_name: string;
}

interface Track {
  track_id: number;
  track_name: string;
}

const COMPOUNDS = [
  { value: 'soft', label: 'Soft', color: 'text-safety-red' },
  { value: 'medium', label: 'Medium', color: 'text-marshal-yellow' },
  { value: 'hard', label: 'Hard', color: 'text-chalk' },
  { value: 'wet', label: 'Wet', color: 'text-blue-400' },
  { value: 'inter', label: 'Intermediate', color: 'text-green-400' },
] as const;

export default function NewRaceStrategyPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [trackId, setTrackId] = useState('');
  const [driverId, setDriverId] = useState('');
  const [raceLaps, setRaceLaps] = useState('25');
  const [baseTime, setBaseTime] = useState('65.000');
  const [pitLoss, setPitLoss] = useState('25');
  const [compounds, setCompounds] = useState<Set<string>>(new Set(['soft', 'medium', 'hard']));
  const [fuel, setFuel] = useState('0');
  const [fuelPerLap, setFuelPerLap] = useState('0');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const { data: driversData } = useQuery({
    queryKey: ['drivers'],
    queryFn: () => api.get<{ drivers: Driver[] }>('/drivers'),
  });

  const { data: tracksData } = useQuery({
    queryKey: ['tracks'],
    queryFn: () => api.get<{ tracks: Track[] }>('/tracks'),
  });

  const toggleCompound = (value: string) => {
    setCompounds((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Strategy name is required');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const result = await api.post<{ id: number }>('/race-strategy', {
        name: name.trim(),
        track_id: trackId || null,
        driver_id: driverId || null,
        race_laps: parseInt(raceLaps),
        base_lap_time: parseFloat(baseTime),
        pit_loss_seconds: parseFloat(pitLoss),
        compounds: Array.from(compounds),
        fuel_load_kg: parseFloat(fuel),
        fuel_per_lap_kg: parseFloat(fuelPerLap),
      });
      router.push(`/app/race-strategy/${result.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create strategy');
    } finally {
      setSubmitting(false);
    }
  };

  const drivers = driversData?.drivers ?? [];
  const tracks = tracksData?.tracks ?? [];

  return (
    <div>
      <PageHeader title="New Race Strategy" subtitle="Configure race parameters and constraints" />

      <form onSubmit={handleSubmit} className="max-w-2xl">
        {error && (
          <div className="mb-4 p-3 bg-safety-red/10 border border-safety-red/30 rounded text-safety-red font-body text-sm">
            {error}
          </div>
        )}

        <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
          <h3 className="font-body text-chalk text-lg mb-4">General</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <FormField
              label="Strategy Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Sunday Sprint Race"
              required
            />

            <div>
              <label className="block text-steel font-telemetry text-xs uppercase mb-1">
                Track
              </label>
              <select
                value={trackId}
                onChange={(e) => setTrackId(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
              >
                <option value="">Select track...</option>
                {tracks.map((t) => (
                  <option key={t.track_id} value={t.track_id}>
                    {t.track_name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-steel font-telemetry text-xs uppercase mb-1">
                Driver
              </label>
              <select
                value={driverId}
                onChange={(e) => setDriverId(e.target.value)}
                className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm focus:outline-none focus:border-pit-orange"
              >
                <option value="">Select driver...</option>
                {drivers.map((d) => (
                  <option key={d.driver_id} value={d.driver_id}>
                    {d.driver_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
          <h3 className="font-body text-chalk text-lg mb-4">Race Parameters</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <FormField
              label="Race Distance (laps)"
              type="number"
              value={raceLaps}
              onChange={(e) => setRaceLaps(e.target.value)}
              min={3}
              max={200}
            />
            <FormField
              label="Base Lap Time (s)"
              type="number"
              value={baseTime}
              onChange={(e) => setBaseTime(e.target.value)}
              step={0.001}
              min={10}
              max={600}
            />
            <FormField
              label="Pit Stop Loss (s)"
              type="number"
              value={pitLoss}
              onChange={(e) => setPitLoss(e.target.value)}
              step={0.5}
              min={5}
              max={120}
            />
          </div>
        </div>

        <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
          <h3 className="font-body text-chalk text-lg mb-4">Tyre Compounds</h3>
          <div className="flex flex-wrap gap-3">
            {COMPOUNDS.map((c) => (
              <button
                key={c.value}
                type="button"
                onClick={() => toggleCompound(c.value)}
                className={`px-4 py-2 rounded border font-telemetry text-sm transition-colors ${
                  compounds.has(c.value)
                    ? 'border-acid-green bg-acid-green/10 text-acid-green'
                    : 'border-steel/30 text-steel hover:text-chalk'
                }`}
              >
                <span className={compounds.has(c.value) ? c.color : ''}>
                  {c.label}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
          <h3 className="font-body text-chalk text-lg mb-4">Fuel (Optional)</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <FormField
              label="Starting Fuel (kg)"
              type="number"
              value={fuel}
              onChange={(e) => setFuel(e.target.value)}
              step={0.5}
              min={0}
              max={150}
            />
            <FormField
              label="Consumption (kg/lap)"
              type="number"
              value={fuelPerLap}
              onChange={(e) => setFuelPerLap(e.target.value)}
              step={0.1}
              min={0}
              max={10}
            />
          </div>
        </div>

        <div className="flex justify-between">
          <button
            type="button"
            onClick={() => router.back()}
            className="px-4 py-2 text-steel font-telemetry text-sm hover:text-chalk transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2.5 bg-acid-green text-asphalt font-telemetry text-sm rounded disabled:opacity-50 hover:bg-acid-green/80 transition-colors"
          >
            {submitting ? 'Creating...' : 'Create Strategy'}
          </button>
        </div>
      </form>
    </div>
  );
}
