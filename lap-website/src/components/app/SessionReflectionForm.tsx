'use client';

import { useState } from 'react';
import { api } from '@/lib/api-client';

// Must match backend scoring.contextual.RESULT_TAGS exactly.
const RESULT_TAGS = [
  'completed', 'dnf', 'crashed', 'pit_issue', 'traffic',
  'mechanical', 'tyre_age_high', 'red_flag',
] as const;
type ResultTag = (typeof RESULT_TAGS)[number];

interface Competitor {
  competitor_name: string;
  final_position?: number | null;
  gap_to_this_driver_s?: number | null;
  notes?: string | null;
}

export interface ReflectionInitial {
  result_tags?: string[];
  driver_perceived_conditions?: string | null;
  felt_performance_rating?: number | null;
  race_position?: number | null;
  race_total_competitors?: number | null;
  competitors?: Competitor[];
}

export function SessionReflectionForm({
  sessionId, initial, onSaved,
}: {
  sessionId: string;
  initial: ReflectionInitial | null;
  onSaved: () => void;
}) {
  const [tags, setTags] = useState<Set<ResultTag>>(
    new Set((initial?.result_tags ?? []).filter((t): t is ResultTag =>
      (RESULT_TAGS as readonly string[]).includes(t))),
  );
  const [rating, setRating] = useState<number | ''>(initial?.felt_performance_rating ?? '');
  const [conditions, setConditions] = useState(initial?.driver_perceived_conditions ?? '');
  const [position, setPosition] = useState<number | ''>(initial?.race_position ?? '');
  const [fieldSize, setFieldSize] = useState<number | ''>(initial?.race_total_competitors ?? '');
  const [competitors, setCompetitors] = useState<Competitor[]>(initial?.competitors ?? []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleTag(t: ResultTag) {
    setTags((prev) => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });
  }

  function addCompetitor() {
    setCompetitors((c) => [...c, { competitor_name: '', final_position: null, gap_to_this_driver_s: null }]);
  }

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const res = await api.post<{ saved: boolean; competitors: number }>(
        `/sessions/${sessionId}/reflection`,
        {
          result_tags: Array.from(tags),
          driver_perceived_conditions: conditions || null,
          felt_performance_rating: rating === '' ? null : Number(rating),
          race_position: position === '' ? null : Number(position),
          race_total_competitors: fieldSize === '' ? null : Number(fieldSize),
          competitors: competitors.filter((c) => c.competitor_name.trim()),
        },
      );
      if (res.saved) onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save reflection');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-1">How did it go?</h2>
      <p className="text-xs font-body text-steel mb-4">
        Your reflection adds labeled context to the score — it never silently changes it.
      </p>

      {/* Result tags */}
      <div className="mb-4">
        <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Result</h3>
        <div className="flex flex-wrap gap-2">
          {RESULT_TAGS.map((t) => {
            const on = tags.has(t);
            return (
              <button
                key={t}
                type="button"
                aria-pressed={on}
                onClick={() => toggleTag(t)}
                className={`px-3 py-1 rounded-full text-xs font-telemetry border transition-colors ${
                  on
                    ? 'bg-gold/10 text-gold border-gold/40'
                    : 'text-steel border-steel/30 hover:text-chalk'
                }`}
              >
                {t.replace(/_/g, ' ')}
              </button>
            );
          })}
        </div>
      </div>

      {/* Felt rating + conditions */}
      <div className="mb-4 grid grid-cols-2 gap-4">
        <label className="block">
          <span className="text-xs text-steel font-body">Felt performance (1-10)</span>
          <input
            type="number" min={1} max={10} value={rating}
            onChange={(e) => setRating(e.target.value === '' ? '' : Number(e.target.value))}
            className="mt-1 w-full bg-asphalt border border-steel/30 rounded px-2 py-1
              text-sm font-telemetry text-chalk"
          />
        </label>
        <label className="block">
          <span className="text-xs text-steel font-body">Perceived conditions</span>
          <input
            type="text" value={conditions} placeholder="e.g. damp, drying"
            onChange={(e) => setConditions(e.target.value)}
            className="mt-1 w-full bg-asphalt border border-steel/30 rounded px-2 py-1
              text-sm font-body text-chalk"
          />
        </label>
      </div>

      {/* Race result */}
      <div className="mb-4 grid grid-cols-2 gap-4">
        <label className="block">
          <span className="text-xs text-steel font-body">Finish position</span>
          <input
            type="number" min={1} value={position}
            onChange={(e) => setPosition(e.target.value === '' ? '' : Number(e.target.value))}
            className="mt-1 w-full bg-asphalt border border-steel/30 rounded px-2 py-1
              text-sm font-telemetry text-chalk"
          />
        </label>
        <label className="block">
          <span className="text-xs text-steel font-body">Field size</span>
          <input
            type="number" min={1} value={fieldSize}
            onChange={(e) => setFieldSize(e.target.value === '' ? '' : Number(e.target.value))}
            className="mt-1 w-full bg-asphalt border border-steel/30 rounded px-2 py-1
              text-sm font-telemetry text-chalk"
          />
        </label>
      </div>

      {/* Competitors */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs text-steel font-body uppercase tracking-wider">Rivals</h3>
          <button
            type="button" onClick={addCompetitor}
            className="text-xs font-telemetry text-steel hover:text-chalk"
          >
            + add rival
          </button>
        </div>
        <div className="space-y-2">
          {competitors.map((c, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text" value={c.competitor_name} placeholder="Name"
                onChange={(e) => setCompetitors((prev) =>
                  prev.map((x, j) => (j === i ? { ...x, competitor_name: e.target.value } : x)))}
                className="flex-1 bg-asphalt border border-steel/30 rounded px-2 py-1
                  text-sm font-body text-chalk"
              />
              <input
                type="number" value={c.gap_to_this_driver_s ?? ''} placeholder="gap s" step="0.1"
                onChange={(e) => setCompetitors((prev) =>
                  prev.map((x, j) => (j === i
                    ? { ...x, gap_to_this_driver_s: e.target.value === '' ? null : Number(e.target.value) }
                    : x)))}
                className="w-20 bg-asphalt border border-steel/30 rounded px-2 py-1
                  text-sm font-telemetry text-chalk"
              />
            </div>
          ))}
        </div>
      </div>

      {error && <p className="text-xs text-safety-red font-body mb-2">{error}</p>}

      <button
        type="button" onClick={submit} disabled={saving}
        className="bg-gold text-white hover:bg-gold/80 disabled:opacity-50
          rounded px-4 py-2 text-sm font-telemetry"
      >
        {saving ? 'Saving…' : 'Save reflection'}
      </button>
    </div>
  );
}
