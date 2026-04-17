'use client';

import { useState } from 'react';
import type { ReadinessState, RunLifecycle, SupportTier } from '@/lib/api/bundles/types';

export interface Filters {
  readiness: ReadinessState | null;
  lifecycle: RunLifecycle | null;
  tier: SupportTier | null;
  sim: string | null;
}

const EMPTY: Filters = { readiness: null, lifecycle: null, tier: null, sim: null };

interface Props {
  sims: string[];
  filters: Filters;
  onChange: (f: Filters) => void;
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-xs font-telemetry transition-colors border ${
        active
          ? 'border-gold/50 text-gold bg-gold/10'
          : 'border-steel/20 text-steel hover:border-steel/40'
      }`}
    >
      {label}
    </button>
  );
}

export function FilterBar({ sims, filters, onChange }: Props) {
  const toggle = <K extends keyof Filters>(key: K, value: Filters[K]) => {
    onChange({ ...filters, [key]: filters[key] === value ? null : value });
  };

  const hasActive = Object.values(filters).some((v) => v !== null);

  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      {/* Readiness */}
      {(['ready', 'degraded', 'blocked'] as ReadinessState[]).map((r) => (
        <Chip key={r} label={r} active={filters.readiness === r} onClick={() => toggle('readiness', r)} />
      ))}

      <span className="w-px h-4 bg-steel/20" />

      {/* Lifecycle */}
      {(['uploaded', 'validated', 'analyzed', 'failed'] as RunLifecycle[]).map((l) => (
        <Chip key={l} label={l} active={filters.lifecycle === l} onClick={() => toggle('lifecycle', l)} />
      ))}

      <span className="w-px h-4 bg-steel/20" />

      {/* Tier */}
      {(['full', 'standard', 'limited'] as SupportTier[]).map((t) => (
        <Chip key={t} label={t} active={filters.tier === t} onClick={() => toggle('tier', t)} />
      ))}

      {/* Sim */}
      {sims.length > 1 && (
        <>
          <span className="w-px h-4 bg-steel/20" />
          {sims.map((s) => (
            <Chip key={s} label={s.toUpperCase()} active={filters.sim === s} onClick={() => toggle('sim', s)} />
          ))}
        </>
      )}

      {hasActive && (
        <button
          onClick={() => onChange(EMPTY)}
          className="text-xs font-telemetry text-steel hover:text-chalk transition-colors ml-2"
        >
          Clear
        </button>
      )}
    </div>
  );
}

export function useFilters() {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  return { filters, setFilters };
}
