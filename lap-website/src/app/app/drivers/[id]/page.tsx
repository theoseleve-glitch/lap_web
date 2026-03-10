'use client';

import { useParams, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '@/lib/api-client';
import { queryKeys } from '@/lib/query-keys';
import type {
  DriverDetail, DriverProgression, DriverStyleEntry,
  DriverBadge, DriverBestEver, DriverSession,
} from '@/lib/api-types';
import { StatCard, QueryError, InlineEdit, SkeletonStatCards } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { ProgressionChart } from '@/components/app/drivers/ProgressionChart';
import { StyleRadar } from '@/components/app/drivers/StyleRadar';
import { BadgeGrid } from '@/components/app/drivers/BadgeGrid';
import { DriverSessionsTable } from '@/components/app/drivers/DriverSessionsTable';

/* ── Helpers ───────────────────────────────────────────── */

function fmtTime(s: number | null): string {
  if (s == null) return '\u2014';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
}

const STYLE_COLORS: Record<string, string> = {
  Aggressive: 'bg-safety-red/10 text-safety-red',
  Smooth: 'bg-acid-green/10 text-acid-green',
  Balanced: 'bg-marshal-yellow/10 text-marshal-yellow',
  Conservative: 'bg-blue-400/10 text-blue-400',
};

/* ── Section wrapper ───────────────────────────────────── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-concrete rounded-lg border border-steel/20 p-5">
      <h3 className="font-monument text-sm text-chalk uppercase tracking-wider mb-4">{title}</h3>
      {children}
    </section>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function DriverDetailPage() {
  const { id } = useParams<{ id: string }>();
  const driverId = Number(id);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // ── Queries (parallel) ──────────────────────────────
  const driverQ = useQuery({
    queryKey: queryKeys.drivers.detail(driverId),
    queryFn: () => api.get<DriverDetail>(`/drivers/${driverId}`),
  });

  const progressionQ = useQuery({
    queryKey: queryKeys.drivers.progression(driverId),
    queryFn: () => api.get<{ progression: DriverProgression[] }>(`/drivers/${driverId}/progression`),
    enabled: driverQ.isSuccess,
  });

  const styleQ = useQuery({
    queryKey: queryKeys.drivers.styleHistory(driverId),
    queryFn: () => api.get<{ history: DriverStyleEntry[] }>(`/drivers/${driverId}/style-history`),
    enabled: driverQ.isSuccess,
  });

  const badgesQ = useQuery({
    queryKey: queryKeys.drivers.badges(driverId),
    queryFn: () => api.get<{ badges: DriverBadge[] }>(`/drivers/${driverId}/badges`),
    enabled: driverQ.isSuccess,
  });

  const bestEverQ = useQuery({
    queryKey: queryKeys.drivers.bestEver(driverId),
    queryFn: () => api.get<DriverBestEver>(`/drivers/${driverId}/best-ever`),
    enabled: driverQ.isSuccess,
  });

  const sessionsQ = useQuery({
    queryKey: queryKeys.drivers.sessions(driverId),
    queryFn: () => api.get<{ sessions: DriverSession[] }>(`/drivers/${driverId}/sessions`),
    enabled: driverQ.isSuccess,
  });

  // ── Mutations ───────────────────────────────────────
  async function saveName(newName: string) {
    await api.patch(`/drivers/${driverId}`, { name: newName });
    queryClient.invalidateQueries({ queryKey: queryKeys.drivers.detail(driverId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.drivers.all });
  }

  async function saveNotes(newNotes: string) {
    await api.patch(`/drivers/${driverId}`, { notes: newNotes });
    queryClient.invalidateQueries({ queryKey: queryKeys.drivers.detail(driverId) });
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await api.delete(`/drivers/${driverId}`);
      queryClient.invalidateQueries({ queryKey: queryKeys.drivers.all });
      router.push('/app/drivers');
    } catch {
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  }

  // ── Loading / Error ─────────────────────────────────
  if (driverQ.isLoading) {
    return (
      <div>
        <PageIntro title="Driver" subtitle="Loading..." />
        <SkeletonStatCards count={5} />
      </div>
    );
  }

  if (driverQ.error) {
    return <QueryError message="Couldn't load driver." onRetry={() => driverQ.refetch()} />;
  }

  const driver = driverQ.data!;
  const progression = progressionQ.data?.progression ?? [];
  const styleHistory = styleQ.data?.history ?? [];
  const latestStyle = styleHistory.length > 0 ? styleHistory[styleHistory.length - 1] : null;
  const badges = badgesQ.data?.badges ?? [];
  const bestEver = bestEverQ.data;
  const sessions = sessionsQ.data?.sessions ?? [];

  return (
    <div className="space-y-6">

      {/* ── Header ─────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <InlineEdit
            value={driver.name}
            onSave={saveName}
            placeholder="Driver name"
          />
          <div className="mt-2">
            <InlineEdit
              value={driver.notes ?? ''}
              onSave={saveNotes}
              placeholder="Add notes..."
              multiline
              className="[&_button>span]:!font-body [&_button>span]:!text-sm [&_button>span]:!text-steel [&_button>span]:!font-normal"
            />
          </div>
        </div>
        {driver.style_label && (
          <span className={`px-3 py-1 rounded text-xs font-telemetry uppercase ${
            STYLE_COLORS[driver.style_label] ?? 'bg-steel/10 text-steel'
          }`}>
            {driver.style_label}
          </span>
        )}
      </div>

      {/* ── Stats Bar ──────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard label="Sessions" value={driver.session_count} />
        <StatCard label="Total Laps" value={driver.total_laps} />
        <StatCard label="Personal Best" value={fmtTime(driver.personal_best_s)} />
        <StatCard label="Avg Score" value={driver.mean_score?.toFixed(1) ?? '\u2014'} unit="/100" />
        <StatCard
          label="vs Track Record"
          value={bestEver?.best_pct != null ? `${bestEver.best_pct}%` : '\u2014'}
        />
      </div>

      {/* ── Records Held ───────────────────────────────── */}
      {bestEver && bestEver.records_held.length > 0 && (
        <Section title="Track Records Held">
          <div className="flex flex-wrap gap-3">
            {bestEver.records_held.map((r, i) => (
              <div key={i} className="bg-carbon rounded px-3 py-2 border border-acid-green/20">
                <p className="font-telemetry text-xs text-acid-green">
                  {(r as Record<string, string>).track_name ?? 'Unknown'}
                </p>
                <p className="font-telemetry text-[10px] text-steel/60">
                  {fmtTime((r as Record<string, number>).record_time_s ?? null)}
                </p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Progression ────────────────────────────────── */}
      <Section title="Progression">
        {progressionQ.isLoading ? (
          <div className="h-48 animate-pulse bg-steel/5 rounded" />
        ) : (
          <ProgressionChart data={progression} />
        )}
      </Section>

      {/* ── Driving Style ──────────────────────────────── */}
      <Section title="Driving Style">
        {styleQ.isLoading ? (
          <div className="h-48 animate-pulse bg-steel/5 rounded" />
        ) : (
          <StyleRadar latest={latestStyle} history={styleHistory} />
        )}
      </Section>

      {/* ── Badges ─────────────────────────────────────── */}
      <Section title="Badges">
        {badgesQ.isLoading ? (
          <div className="h-24 animate-pulse bg-steel/5 rounded" />
        ) : (
          <BadgeGrid badges={badges} />
        )}
      </Section>

      {/* ── Sessions ───────────────────────────────────── */}
      <Section title="Sessions">
        {sessionsQ.isLoading ? (
          <div className="h-32 animate-pulse bg-steel/5 rounded" />
        ) : (
          <DriverSessionsTable sessions={sessions} />
        )}
      </Section>

      {/* ── Danger Zone ────────────────────────────────── */}
      <section className="bg-concrete rounded-lg border border-safety-red/20 p-5">
        <h3 className="font-monument text-sm text-safety-red uppercase tracking-wider mb-3">Danger Zone</h3>
        {showDeleteConfirm ? (
          <div className="flex items-center gap-3">
            <p className="text-chalk font-body text-sm">
              Delete <strong>{driver.name}</strong> and all their sessions? This cannot be undone.
            </p>
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="px-4 py-2 bg-safety-red text-white font-telemetry text-xs rounded
                hover:bg-safety-red/80 disabled:opacity-50 transition-colors"
            >
              {deleting ? 'Deleting...' : 'Confirm Delete'}
            </button>
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(false)}
              className="px-4 py-2 bg-steel/10 text-steel font-telemetry text-xs rounded
                hover:bg-steel/20 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(true)}
            className="px-4 py-2 border border-safety-red/40 text-safety-red font-telemetry text-xs rounded
              hover:bg-safety-red/10 transition-colors"
          >
            Delete Driver
          </button>
        )}
      </section>
    </div>
  );
}
