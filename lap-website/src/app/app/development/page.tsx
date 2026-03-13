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
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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

  /* Delete mutation */
  const deleteMutation = useMutation({
    mutationFn: (planId: number) => api.delete(`/dev-plans/${planId}`),
    onMutate: async (planId) => {
      setDeleteError(null);
      await queryClient.cancelQueries({ queryKey: ['dev-plans'] });
      const prev = queryClient.getQueryData<DevPlan[]>(['dev-plans', driverFilter]);
      queryClient.setQueryData<DevPlan[]>(['dev-plans', driverFilter], (old) =>
        old ? old.filter((p) => p.id !== planId) : [],
      );
      setConfirmDelete(null);
      return { prev };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dev-plans'] });
    },
    onError: (_err, _id, context) => {
      if (context?.prev) queryClient.setQueryData(['dev-plans', driverFilter], context.prev);
      setDeleteError(_err instanceof Error ? _err.message : 'Failed to delete plan');
    },
  });

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

      {/* -- Delete Error ------------------------------------- */}
      {deleteError && (
        <div className="flex items-center justify-between bg-safety-red/10 border border-safety-red/30 rounded-lg px-4 py-2 mb-4">
          <p className="text-safety-red font-telemetry text-xs">{deleteError}</p>
          <button type="button" onClick={() => setDeleteError(null)} className="text-safety-red/60 hover:text-safety-red text-xs ml-3">dismiss</button>
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
              {/* Name + Status badge + delete */}
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-monument text-lg text-chalk group-hover:text-acid-green transition-colors truncate">
                  {plan.plan_name}
                </h3>
                <div className="flex items-center gap-2 shrink-0">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-telemetry uppercase border ${statusBadgeClass(plan.status)}`}
                  >
                    {plan.status}
                  </span>
                  {confirmDelete === plan.id ? (
                    <span className="inline-flex items-center gap-1" onClick={(e) => e.preventDefault()}>
                      <button
                        type="button"
                        onClick={(e) => { e.preventDefault(); deleteMutation.mutate(plan.id); }}
                        disabled={deleteMutation.isPending}
                        className="px-2 py-0.5 text-[10px] font-telemetry uppercase bg-safety-red/20 text-safety-red border border-safety-red/40 rounded hover:bg-safety-red/30 transition-colors disabled:opacity-50"
                      >
                        {deleteMutation.isPending ? 'Deleting...' : 'Confirm'}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.preventDefault(); setConfirmDelete(null); setDeleteError(null); }}
                        disabled={deleteMutation.isPending}
                        className="px-1.5 py-0.5 text-[10px] font-telemetry text-steel hover:text-chalk transition-colors disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={(e) => { e.preventDefault(); setConfirmDelete(plan.id); }}
                      title="Delete plan"
                      className="p-1 text-steel/40 hover:text-safety-red transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                      </svg>
                    </button>
                  )}
                </div>
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
