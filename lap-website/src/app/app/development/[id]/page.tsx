'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useState, useMemo, useCallback } from 'react';
import { api } from '@/lib/api-client';
import { PageHeader, QueryError, SkeletonBox } from '@/components/app';

/* -- Types -------------------------------------------------- */

interface ProgressItem {
  text: string;
  done: boolean;
}

interface ProgressJson {
  items: ProgressItem[];
}

interface DevPlanDetail {
  id: number;
  driver_id: number;
  plan_name: string;
  template_id: string | null;
  level: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  progress_json: string | ProgressJson | null;
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

function parseProgress(raw: string | ProgressJson | null): ProgressJson {
  if (!raw) return { items: [] };
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.items)) return parsed as ProgressJson;
      return { items: [] };
    } catch {
      return { items: [] };
    }
  }
  if (Array.isArray(raw.items)) return raw;
  return { items: [] };
}

/* -- Page ---------------------------------------------------- */

export default function DevelopmentPlanDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const planId = params.id;

  const [newItemText, setNewItemText] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  /* Fetch plan detail */
  const {
    data: plan,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['dev-plan', planId],
    queryFn: () => api.get<DevPlanDetail>(`/dev-plans/${planId}`),
    enabled: !!planId,
  });

  /* Parse progress */
  const progress = useMemo(() => parseProgress(plan?.progress_json ?? null), [plan]);

  /* PATCH mutation for progress updates */
  const patchMutation = useMutation({
    mutationFn: (progressJson: ProgressJson) =>
      api.patch<DevPlanDetail>(`/dev-plans/${planId}`, {
        progress_json: JSON.stringify(progressJson),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dev-plan', planId] });
    },
  });

  /* DELETE mutation */
  const deleteMutation = useMutation({
    mutationFn: () => api.delete<void>(`/dev-plans/${planId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dev-plans'] });
      router.push('/app/development');
    },
  });

  /* Toggle item done/undone */
  const toggleItem = useCallback(
    (index: number) => {
      const updated: ProgressJson = {
        items: progress.items.map((item, i) =>
          i === index ? { ...item, done: !item.done } : item,
        ),
      };
      patchMutation.mutate(updated);
    },
    [progress, patchMutation],
  );

  /* Add new item */
  const addItem = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!newItemText.trim()) return;
      const updated: ProgressJson = {
        items: [...progress.items, { text: newItemText.trim(), done: false }],
      };
      patchMutation.mutate(updated);
      setNewItemText('');
    },
    [progress, newItemText, patchMutation],
  );

  /* Remove item */
  const removeItem = useCallback(
    (index: number) => {
      const updated: ProgressJson = {
        items: progress.items.filter((_, i) => i !== index),
      };
      patchMutation.mutate(updated);
    },
    [progress, patchMutation],
  );

  /* Progress percentage */
  const completedCount = progress.items.filter((item) => item.done).length;
  const totalCount = progress.items.length;
  const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  /* Loading state */
  if (isLoading) {
    return (
      <div>
        <div className="mb-6">
          <SkeletonBox className="h-8 w-64 mb-2" />
          <SkeletonBox className="h-4 w-40" />
        </div>
        <SkeletonBox className="h-48 w-full" />
      </div>
    );
  }

  /* Error state */
  if (error) {
    return <QueryError message="Couldn't load this development plan." onRetry={() => refetch()} />;
  }

  /* Plan not found */
  if (!plan) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Plan not found</h2>
        <Link href="/app/development" className="text-pit-orange font-telemetry text-sm hover:underline">
          Back to Development Plans
        </Link>
      </div>
    );
  }

  return (
    <div>
      {/* Back link */}
      <Link
        href="/app/development"
        className="inline-flex items-center gap-1 text-steel hover:text-chalk font-telemetry text-xs mb-4 transition-colors"
      >
        &larr; Back to Development Plans
      </Link>

      <PageHeader
        title={plan.plan_name}
        subtitle={`Driver #${plan.driver_id}`}
        actions={
          <span
            className={`px-3 py-1 rounded text-xs font-telemetry uppercase border ${statusBadgeClass(plan.status)}`}
          >
            {plan.status}
          </span>
        }
      />

      {/* -- Metadata ---------------------------------------- */}
      <div className="flex flex-wrap gap-4 text-steel font-telemetry text-xs mb-6">
        <span>Created: {formatDate(plan.created_at)}</span>
        <span>Updated: {formatDate(plan.updated_at)}</span>
        {plan.level && <span>Level: {plan.level}</span>}
        {plan.template_id && <span>Template: {plan.template_id}</span>}
      </div>

      {/* -- Progress Bar ------------------------------------ */}
      {totalCount > 0 && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-5 mb-6">
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-monument text-sm text-chalk">Progress</h2>
            <span className="font-telemetry text-xs text-steel">
              {completedCount}/{totalCount} items ({progressPercent}%)
            </span>
          </div>
          <div className="w-full h-2 bg-steel/10 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-acid-green transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      {/* -- Progress Checklist ------------------------------ */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-5 mb-6">
        <h2 className="font-monument text-sm text-chalk mb-4">Checklist</h2>

        {progress.items.length === 0 ? (
          <p className="text-steel font-body text-sm mb-4">
            No items yet. Add items below to track your progress.
          </p>
        ) : (
          <ul className="space-y-2 mb-4">
            {progress.items.map((item, index) => (
              <li
                key={index}
                className="flex items-center gap-3 group"
              >
                <button
                  type="button"
                  onClick={() => toggleItem(index)}
                  disabled={patchMutation.isPending}
                  className={`shrink-0 w-5 h-5 rounded border transition-colors flex items-center justify-center ${
                    item.done
                      ? 'bg-gold border-acid-green text-asphalt'
                      : 'border-steel/40 hover:border-acid-green/60'
                  }`}
                  aria-label={item.done ? `Mark "${item.text}" as incomplete` : `Mark "${item.text}" as complete`}
                >
                  {item.done && (
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </button>
                <span
                  className={`flex-1 font-body text-sm transition-colors ${
                    item.done ? 'line-through text-steel/50' : 'text-chalk'
                  }`}
                >
                  {item.text}
                </span>
                <button
                  type="button"
                  onClick={() => removeItem(index)}
                  disabled={patchMutation.isPending}
                  className="opacity-0 group-hover:opacity-100 shrink-0 text-steel hover:text-safety-red
                    font-telemetry text-xs transition-all"
                  aria-label={`Remove "${item.text}"`}
                >
                  x
                </button>
              </li>
            ))}
          </ul>
        )}

        {/* Add item form */}
        <form onSubmit={addItem} className="flex gap-2">
          <input
            type="text"
            placeholder="Add a checklist item..."
            value={newItemText}
            onChange={(e) => setNewItemText(e.target.value)}
            className="flex-1 min-w-0 bg-asphalt border border-steel/30 rounded px-3 py-2 text-chalk font-body text-sm
              placeholder:text-steel/50 focus:outline-none focus:border-pit-orange focus:ring-1 focus:ring-pit-orange/50"
          />
          <button
            type="submit"
            disabled={!newItemText.trim() || patchMutation.isPending}
            className="px-4 py-2 bg-acid-green/20 text-acid-green border border-acid-green/30 font-telemetry text-xs rounded
              hover:bg-gold/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Add
          </button>
        </form>
      </div>

      {/* -- Delete ------------------------------------------ */}
      <div className="bg-concrete rounded-lg border border-safety-red/20 p-5">
        <h2 className="font-monument text-sm text-chalk mb-2">Danger Zone</h2>
        {showDeleteConfirm ? (
          <div className="flex items-center gap-3">
            <p className="text-safety-red font-body text-sm">
              Are you sure? This cannot be undone.
            </p>
            <button
              type="button"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 bg-safety-red text-chalk font-telemetry text-xs rounded
                hover:bg-safety-red/80 transition-colors disabled:opacity-50"
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Yes, delete'}
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
            className="px-4 py-2 bg-safety-red/10 text-safety-red border border-safety-red/30 font-telemetry text-xs rounded
              hover:bg-safety-red/20 transition-colors"
          >
            Delete this plan
          </button>
        )}
        {deleteMutation.isError && (
          <p className="mt-2 text-safety-red font-body text-xs">
            Failed to delete plan. Please try again.
          </p>
        )}
      </div>
    </div>
  );
}
