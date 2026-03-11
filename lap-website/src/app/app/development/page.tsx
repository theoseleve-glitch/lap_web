'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useState, useMemo } from 'react';
import { api } from '@/lib/api-client';
import { QueryError, SkeletonCardGrid } from '@/components/app';
import { PageIntro } from '@/components/ui/PageIntro';
import { XPProgressBar, StreakCounter } from '@/components/app/gamification';
import type { DriverProgress } from '@/components/app/gamification';

/* -- Types -------------------------------------------------- */

interface DevPlan {
  id: number;
  driver_id: number;
  plan_name: string;
  template_id: string | null;
  level: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

interface DriverRow {
  id: number;
  name: string;
}

/* -- Helpers ------------------------------------------------- */

function formatDate(iso: string): string {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  active: 'bg-acid-green/10 text-acid-green border-acid-green/30',
  completed: 'bg-blue-400/10 text-blue-400 border-blue-400/30',
};

function statusBadgeClass(status: string): string {
  return STATUS_STYLES[status] ?? 'bg-steel/10 text-steel border-steel/30';
}

/* -- Page ---------------------------------------------------- */

export default function DevelopmentPlansPage() {
  const queryClient = useQueryClient();

  const [driverFilter, setDriverFilter] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formDriverId, setFormDriverId] = useState<number | ''>('');

  /* Queries */
  const {
    data: plansData,
    isLoading: plansLoading,
    error: plansError,
    refetch: refetchPlans,
  } = useQuery({
    queryKey: ['dev-plans', driverFilter],
    queryFn: () => {
      const params = driverFilter ? `?driver_id=${driverFilter}` : '';
      return api.get<DevPlan[]>(`/dev-plans${params}`);
    },
  });

  const { data: driversData } = useQuery({
    queryKey: ['drivers-list'],
    queryFn: () => api.get<DriverRow[]>('/drivers'),
  });

  const { data: driverProgress } = useQuery({
    queryKey: ['driver-gamification', driverFilter],
    queryFn: () => api.get<DriverProgress>(`/drivers/${driverFilter}/progress`),
    enabled: driverFilter != null,
  });

  const plans = Array.isArray(plansData) ? plansData : [];
  const drivers = Array.isArray(driversData) ? driversData : [];

  /* Driver lookup map */
  const driverMap = useMemo(() => {
    const m = new Map<number, string>();
    for (const d of drivers) {
      m.set(d.id, d.name);
    }
    return m;
  }, [drivers]);

  /* Create mutation */
  const createMutation = useMutation({
    mutationFn: (body: { driver_id: number; plan_name: string }) =>
      api.post<DevPlan>('/dev-plans', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dev-plans'] });
      setShowForm(false);
      setFormName('');
      setFormDriverId('');
    },
  });

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!formName.trim() || formDriverId === '') return;
    createMutation.mutate({ driver_id: Number(formDriverId), plan_name: formName.trim() });
  }

  /* Filtered list */
  const filtered = useMemo(() => {
    return [...plans].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
  }, [plans]);

  return (
    <div>
      <PageIntro
        title="Development Plans"
        subtitle={`${plans.length} plan${plans.length !== 1 ? 's' : ''}`}
        actions={
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="px-4 py-2 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
          >
            {showForm ? 'Cancel' : '+ New Plan'}
          </button>
        }
      />

      {/* -- Create Form (inline collapsible) ---------------- */}
      {showForm && (
        <form
          onSubmit={handleCreate}
          className="bg-concrete rounded-lg border border-steel/20 p-5 mb-6"
        >
          <h2 className="font-monument text-lg text-chalk mb-4">Create Development Plan</h2>
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              placeholder="Plan name..."
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              required
              className="flex-1 min-w-0 bg-asphalt border border-steel/30 rounded px-4 py-2.5 text-chalk font-body text-sm
                placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
            />
            <select
              value={formDriverId}
              onChange={(e) => setFormDriverId(e.target.value ? Number(e.target.value) : '')}
              required
              className="sm:w-52 bg-asphalt border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
                focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
            >
              <option value="">Select driver...</option>
              {drivers.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-6 py-2.5 bg-gold text-asphalt font-telemetry text-sm rounded
                hover:bg-gold/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </button>
          </div>
          {createMutation.isError && (
            <p className="mt-2 text-safety-red font-body text-xs">
              Failed to create plan. Please try again.
            </p>
          )}
        </form>
      )}

      {/* -- Driver Filter ----------------------------------- */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <select
          value={driverFilter ?? ''}
          onChange={(e) => setDriverFilter(e.target.value ? Number(e.target.value) : null)}
          className="sm:w-52 bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
            focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
        >
          <option value="">All Drivers</option>
          {drivers.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>

      {/* -- Driver XP (when filtered) ----------------------- */}
      {driverFilter != null && driverProgress && driverProgress.total_xp > 0 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-5 mb-6">
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
            <XPProgressBar
              totalXp={driverProgress.total_xp}
              level={driverProgress.level}
              xpForCurrentLevel={driverProgress.xp_for_current_level}
              xpForNextLevel={driverProgress.xp_for_next_level}
              className="flex-1 min-w-0"
            />
            <StreakCounter
              currentStreak={driverProgress.current_streak}
              longestStreak={driverProgress.longest_streak}
            />
          </div>
        </div>
      )}

      {/* -- Content ----------------------------------------- */}
      {plansLoading ? (
        <SkeletonCardGrid count={6} cols={3} />
      ) : plansError ? (
        <QueryError message="Couldn't load development plans." onRetry={() => refetchPlans()} />
      ) : filtered.length === 0 ? (
        <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
          <h2 className="font-monument text-lg text-chalk mb-2">No development plans yet</h2>
          <p className="text-steel font-body text-sm max-w-md mx-auto">
            No development plans yet. Create one to track your improvement goals.
          </p>
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="inline-block mt-4 px-6 py-2.5 bg-pit-orange text-asphalt font-telemetry text-sm rounded hover:bg-pit-orange/80 transition-colors"
          >
            Create First Plan
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((plan) => (
            <Link
              key={plan.id}
              href={`/app/development/${plan.id}`}
              className="group text-left bg-concrete rounded-lg border border-steel/20 p-5
                hover:border-acid-green/40 transition-all cursor-pointer"
            >
              {/* Name + Status badge */}
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                  {plan.plan_name}
                </h3>
                <span
                  className={`shrink-0 px-2 py-0.5 rounded text-[10px] font-telemetry uppercase border ${statusBadgeClass(plan.status)}`}
                >
                  {plan.status}
                </span>
              </div>

              {/* Driver */}
              <p className="text-steel font-body text-sm mt-1 truncate">
                {driverMap.get(plan.driver_id) ?? `Driver #${plan.driver_id}`}
              </p>

              {/* Metadata */}
              <div className="flex items-center gap-3 mt-2 text-steel font-telemetry text-xs">
                <span>Created {formatDate(plan.created_at)}</span>
                {plan.level && (
                  <>
                    <span className="text-steel/60">|</span>
                    <span>{plan.level}</span>
                  </>
                )}
              </div>

              <div className="mt-3 text-right">
                <span className="text-steel/50 font-telemetry text-xs group-hover:text-acid-green transition-colors">
                  View plan &rarr;
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
