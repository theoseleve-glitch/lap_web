'use client';

import type { ReadinessState, ResolutionState, RunLifecycle, SupportTier } from '@/lib/api/bundles/types';

// ── Generic colored badge ──────────────────────────────────

interface BadgeProps {
  label: string;
  color: string;
}

function Badge({ label, color }: BadgeProps) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-telemetry border-${color}/30 text-${color} bg-${color}/10`}>
      {label}
    </span>
  );
}

// ── Typed badges ───────────────────────────────────────────

const TIER_BADGES: Record<SupportTier, BadgeProps> = {
  full: { label: 'Full Analysis', color: 'acid-green' },
  standard: { label: 'Standard', color: 'gold' },
  limited: { label: 'Limited', color: 'marshal-yellow' },
};

export function SupportTierBadge({ tier }: { tier: SupportTier | null }) {
  if (!tier) return null;
  return <Badge {...TIER_BADGES[tier]} />;
}

const READINESS_BADGES: Record<ReadinessState, BadgeProps> = {
  ready: { label: 'Ready', color: 'acid-green' },
  degraded: { label: 'Degraded', color: 'marshal-yellow' },
  blocked: { label: 'Blocked', color: 'safety-red' },
};

export function ReadinessBadge({ state }: { state: ReadinessState }) {
  return <Badge {...READINESS_BADGES[state]} />;
}

const RESOLUTION_BADGES: Record<ResolutionState, BadgeProps> = {
  resolved: { label: 'Resolved', color: 'acid-green' },
  unresolved: { label: 'Unresolved', color: 'marshal-yellow' },
};

export function ResolutionBadge({ state }: { state: ResolutionState }) {
  return <Badge {...RESOLUTION_BADGES[state]} />;
}

const LIFECYCLE_BADGES: Record<RunLifecycle, BadgeProps> = {
  uploaded: { label: 'Uploaded', color: 'steel' },
  validated: { label: 'Analyzing...', color: 'gold' },
  analyzed: { label: 'Analyzed', color: 'acid-green' },
  failed: { label: 'Failed', color: 'safety-red' },
};

export function RunLifecycleBadge({ state }: { state: RunLifecycle | null }) {
  if (!state) return <span className="text-xs font-telemetry text-steel">No analysis</span>;
  return <Badge {...LIFECYCLE_BADGES[state]} />;
}
