'use client';

import type { SessionPresentation } from '@/lib/api/bundles/types';
import { ResolutionBadge, ReadinessBadge } from './StatusBadge';

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function formatDuration(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}m ${sec}s`;
}

export function IdentityBlock({ session }: { session: SessionPresentation }) {
  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-monument text-chalk">
          {session.trackName ?? 'Unknown Track'}
        </h2>
        <div className="flex gap-2">
          <ResolutionBadge state={session.resolution} />
          <ReadinessBadge state={session.readiness} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <Field label="Vehicle" value={session.vehicleName} />
        <Field label="Sim" value={session.sim?.toUpperCase()} />
        <Field label="Session" value={session.sessionType} />
        <Field label="Date" value={formatDate(session.startedAt)} />
        <Field label="Laps" value={String(session.lapCount)} />
        <Field label="Duration" value={formatDuration(session.durationS)} />
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <span className="font-body text-steel">{label}</span>
      <p className={`font-telemetry ${value ? 'text-chalk' : 'text-steel/40 italic'}`}>
        {value || 'Unknown'}
      </p>
    </div>
  );
}
