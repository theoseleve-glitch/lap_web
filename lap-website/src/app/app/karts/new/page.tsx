'use client';

import { useState, useId } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api-client';
import { PageHeader, FormField } from '@/components/app';

interface NewKartPayload {
  name: string;
  number: string;
  chassis: string;
  model: string;
  engine: string;
  power_hp: string;
  weight_kg: string;
  notes: string;
}

interface KartCreated {
  id: number;
}

interface PresetKart {
  segment: string;
  manufacturer: string;
  model: string;
  model_year: number;
  use: string;
  engine: string;
  power_hp: number;
  engine_type: string;
  weight_kg: number;
  top_speed_kmh: number;
}

interface PredefinedKartsResponse {
  segments: Record<string, PresetKart[]>;
  count: number;
}

export default function NewKartPage() {
  const router = useRouter();
  const fieldId = useId();
  const [form, setForm] = useState<NewKartPayload>({
    name: '',
    number: '',
    chassis: '',
    model: '',
    engine: '',
    power_hp: '',
    weight_kg: '',
    notes: '',
  });
  const [errors, setErrors] = useState<Partial<NewKartPayload>>({});
  const [presetMode, setPresetMode] = useState(true);
  const [selectedSegment, setSelectedSegment] = useState('RENTAL');

  const { data: presets } = useQuery({
    queryKey: ['predefined-karts'],
    queryFn: () => api.get<PredefinedKartsResponse>('/predefined-karts'),
  });

  const segments = presets?.segments ?? {};
  const segmentKeys = Object.keys(segments);
  const currentKarts = segments[selectedSegment] ?? [];

  const handlePresetSelect = (preset: PresetKart) => {
    setForm({
      name: `${preset.manufacturer} ${preset.model}`,
      number: '',
      chassis: preset.manufacturer,
      model: preset.model,
      engine: preset.engine,
      power_hp: String(preset.power_hp),
      weight_kg: String(preset.weight_kg),
      notes: `${preset.use} | ${preset.engine_type} | ${preset.top_speed_kmh} km/h top speed`,
    });
    setPresetMode(false);
  };

  const mutation = useMutation({
    mutationFn: (payload: NewKartPayload) =>
      api.post<KartCreated>('/karts', {
        name: payload.name,
        number: payload.number || null,
        chassis: payload.chassis || null,
        model: payload.model || null,
        engine: payload.engine || null,
        power_hp: payload.power_hp ? parseFloat(payload.power_hp) : null,
        weight_kg: payload.weight_kg ? parseFloat(payload.weight_kg) : null,
        notes: payload.notes || null,
      }),
    onSuccess: (data) => {
      router.push(`/app/karts/${data.id}`);
    },
  });

  const handleChange =
    (field: keyof NewKartPayload) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
      if (errors[field]) {
        setErrors((prev) => ({ ...prev, [field]: undefined }));
      }
    };

  const validate = (): boolean => {
    const newErrors: Partial<NewKartPayload> = {};
    if (!form.name.trim()) newErrors.name = 'Name is required';
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    mutation.mutate(form);
  };

  return (
    <div className="max-w-2xl">
      <PageHeader
        title="New Kart"
        subtitle="Add a kart to your fleet"
        actions={
          <button
            onClick={() => router.back()}
            className="px-4 py-2 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
          >
            &larr; Back
          </button>
        }
      />

      {/* Mode toggle */}
      <div className="flex gap-2 mb-4">
        <button
          type="button"
          onClick={() => setPresetMode(true)}
          className={`px-4 py-2 font-telemetry text-sm rounded transition-colors ${
            presetMode
              ? 'bg-acid-green text-asphalt'
              : 'bg-concrete border border-steel/30 text-steel hover:text-chalk'
          }`}
        >
          From Catalogue
        </button>
        <button
          type="button"
          onClick={() => setPresetMode(false)}
          className={`px-4 py-2 font-telemetry text-sm rounded transition-colors ${
            !presetMode
              ? 'bg-acid-green text-asphalt'
              : 'bg-concrete border border-steel/30 text-steel hover:text-chalk'
          }`}
        >
          Custom Kart
        </button>
      </div>

      {presetMode ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6">
          <h2 className="font-body text-chalk text-lg mb-4">Select from catalogue</h2>

          {/* Segment tabs */}
          <div className="flex gap-2 mb-4">
            {segmentKeys.map((seg) => (
              <button
                key={seg}
                type="button"
                onClick={() => setSelectedSegment(seg)}
                className={`px-3 py-1.5 font-telemetry text-xs rounded transition-colors ${
                  selectedSegment === seg
                    ? 'bg-pit-orange text-asphalt'
                    : 'bg-asphalt border border-steel/30 text-steel hover:text-chalk'
                }`}
              >
                {seg} ({segments[seg]?.length ?? 0})
              </button>
            ))}
          </div>

          {/* Kart list */}
          <div className="max-h-96 overflow-y-auto space-y-1">
            {currentKarts.map((k, i) => (
              <button
                key={`${k.manufacturer}-${k.model}-${i}`}
                type="button"
                onClick={() => handlePresetSelect(k)}
                className="w-full text-left px-4 py-3 rounded border border-steel/10 hover:border-acid-green/40 hover:bg-acid-green/5 transition-colors group"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-chalk font-body text-sm group-hover:text-acid-green transition-colors">
                      {k.manufacturer} {k.model}
                    </span>
                    <span className="text-steel font-telemetry text-xs ml-2">({k.model_year})</span>
                  </div>
                  <span className="text-steel font-telemetry text-xs">{k.power_hp} hp / {k.weight_kg} kg</span>
                </div>
                <div className="text-steel font-telemetry text-xs mt-0.5">
                  {k.engine} &middot; {k.top_speed_kmh} km/h
                </div>
              </button>
            ))}
            {currentKarts.length === 0 && (
              <p className="text-steel font-body text-sm text-center py-4">No presets available.</p>
            )}
          </div>
        </div>
      ) : (
        <form
          onSubmit={handleSubmit}
          className="bg-concrete rounded-lg border border-steel/20 p-6 space-y-1"
        >
          <FormField
            label="Name"
            placeholder="e.g. My Kart / Team Kart #1"
            value={form.name}
            onChange={handleChange('name')}
            error={errors.name}
            required
          />
          <FormField
            label="Number"
            placeholder="e.g. 42"
            value={form.number}
            onChange={handleChange('number')}
          />
          <FormField
            label="Manufacturer"
            placeholder="e.g. Tony Kart / Sodikart"
            value={form.chassis}
            onChange={handleChange('chassis')}
          />
          <FormField
            label="Model"
            placeholder="e.g. Racer 401R"
            value={form.model}
            onChange={handleChange('model')}
          />
          <FormField
            label="Engine"
            placeholder="e.g. IAME X30 125cc"
            value={form.engine}
            onChange={handleChange('engine')}
          />
          <div className="grid grid-cols-2 gap-4">
            <FormField
              label="Power (hp)"
              type="number"
              placeholder="e.g. 34"
              value={form.power_hp}
              onChange={handleChange('power_hp')}
              min="0"
              step="0.1"
            />
            <FormField
              label="Weight (kg)"
              type="number"
              placeholder="e.g. 75"
              value={form.weight_kg}
              onChange={handleChange('weight_kg')}
              min="0"
              step="0.1"
            />
          </div>

          <div className="mb-4">
            <label htmlFor={`${fieldId}-notes`} className="block text-steel font-telemetry text-xs uppercase tracking-wider mb-1.5">
              Notes
            </label>
            <textarea
              id={`${fieldId}-notes`}
              className="w-full bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50
                transition-colors resize-none"
              placeholder="Optional notes about this kart..."
              rows={3}
              value={form.notes}
              onChange={handleChange('notes')}
            />
          </div>

          {mutation.error && (
            <p className="text-safety-red font-telemetry text-sm py-2">
              {(mutation.error as Error).message}
            </p>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-6 py-2.5 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {mutation.isPending ? 'Saving...' : 'Save Kart'}
            </button>
            <button
              type="button"
              onClick={() => router.back()}
              className="px-6 py-2.5 border border-steel/30 text-steel font-telemetry text-sm rounded hover:text-chalk hover:border-steel/60 transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
