'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi, type TrainingConfig } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { AdminTable } from '@/components/admin/AdminTable';
import { ActionButton } from '@/components/admin/ActionButton';
import { StatusBadge } from '@/components/admin/StatusBadge';

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export default function TrainingPage() {
  const queryClient = useQueryClient();
  const [editConfig, setEditConfig] = useState(false);
  const [configDraft, setConfigDraft] = useState<Partial<TrainingConfig>>({});

  const { data: status, isLoading } = useQuery({
    queryKey: ['admin-training-status'],
    queryFn: adminApi.trainingStatus,
    refetchInterval: 30000,
  });

  const { data: history } = useQuery({
    queryKey: ['admin-training-history'],
    queryFn: () => adminApi.trainingHistory(10),
  });

  const { data: config } = useQuery({
    queryKey: ['admin-training-config'],
    queryFn: adminApi.trainingConfig,
  });

  const triggerMutation = useMutation({
    mutationFn: (reason: string) => adminApi.triggerTraining(reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-training-status'] });
    },
  });

  const configMutation = useMutation({
    mutationFn: (cfg: Partial<TrainingConfig>) => adminApi.updateTrainingConfig(cfg),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-training-config'] });
      setEditConfig(false);
      setConfigDraft({});
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  const lastRun = status?.last_run;
  const tiers = lastRun?.tiers;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-bold text-chalk">Training Engine</h1>
        <ActionButton
          label="Trigger Training"
          variant="primary"
          onConfirm={async (reason) => {
            await triggerMutation.mutateAsync(reason);
          }}
        />
      </div>

      {/* Status cards */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label="Status"
          value={status?.status === 'never_run' ? 'Never Run' : status?.status ?? 'Unknown'}
          status={status?.status === 'completed' ? 'ok' : status?.status === 'error' ? 'error' : 'warning'}
        />
        <MetricCard
          label="Last Run"
          value={lastRun?.completed_at ? new Date(lastRun.completed_at).toLocaleDateString() : 'N/A'}
          sub={lastRun?.elapsed_s ? formatDuration(lastRun.elapsed_s) : undefined}
          status="ok"
        />
        <MetricCard
          label="Envelopes Trained"
          value={tiers?.envelopes?.trained ?? 0}
          sub={`${tiers?.envelopes?.skipped ?? 0} skipped`}
          status={(tiers?.envelopes?.errors?.length ?? 0) > 0 ? 'warning' : 'ok'}
        />
        <MetricCard
          label="Sessions Reprocessed"
          value={tiers?.reprocess?.succeeded ?? 0}
          sub={`${tiers?.reprocess?.failed ?? 0} failed`}
          status={(tiers?.reprocess?.failed ?? 0) > 0 ? 'warning' : 'ok'}
        />
      </div>

      {/* Global model status */}
      {tiers?.global_model && (
        <div className="mb-6 rounded-lg border border-white/10 bg-concrete p-4">
          <h2 className="mb-2 text-sm font-semibold text-steel">Global Model Bundle</h2>
          <StatusBadge status={tiers.global_model.status} />
          {tiers.global_model.error && (
            <p className="mt-1 text-xs text-red-400">{tiers.global_model.error}</p>
          )}
        </div>
      )}

      {/* Config panel */}
      <div className="mb-6 rounded-lg border border-white/10 bg-concrete p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-steel">Configuration</h2>
          <button
            onClick={() => { setEditConfig(!editConfig); setConfigDraft(config ?? {}); }}
            className="rounded px-2 py-0.5 text-xs text-acid-green hover:bg-gold/10"
          >
            {editConfig ? 'Cancel' : 'Edit'}
          </button>
        </div>
        {config && !editConfig && (
          <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
            <div><span className="text-steel">Schedule:</span> <span className="text-chalk">{DAY_NAMES[config.schedule_day_of_week]} {String(config.schedule_hour).padStart(2,'0')}:{String(config.schedule_minute).padStart(2,'0')} UTC</span></div>
            <div><span className="text-steel">Min Sessions:</span> <span className="text-chalk">{config.min_sessions_per_group}</span></div>
            <div><span className="text-steel">Batch Size:</span> <span className="text-chalk">{config.reprocess_batch_size}</span></div>
            <div><span className="text-steel">Pause Between Batches:</span> <span className="text-chalk">{config.reprocess_pause_s}s</span></div>
          </div>
        )}
        {editConfig && (
          <div className="space-y-2">
            {Object.entries(configDraft).map(([key, val]) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <span className="w-48 text-steel">{key.replace(/_/g, ' ')}</span>
                <input
                  type="number"
                  value={val as number}
                  onChange={(e) => setConfigDraft(d => ({ ...d, [key]: Number(e.target.value) }))}
                  className="w-20 rounded border border-white/10 bg-white/5 px-2 py-0.5 text-chalk"
                />
              </label>
            ))}
            <button
              onClick={() => configMutation.mutate(configDraft)}
              disabled={configMutation.isPending}
              className="mt-2 rounded bg-acid-green/20 px-3 py-1 text-xs text-acid-green hover:bg-gold/30 disabled:opacity-50"
            >
              {configMutation.isPending ? 'Saving...' : 'Save Config'}
            </button>
          </div>
        )}
      </div>

      {/* History table */}
      <h2 className="mb-2 text-sm font-semibold text-steel">Training History</h2>
      <AdminTable
        columns={[
          { key: 'started_at', label: 'Date', render: (r) => r.started_at ? new Date(r.started_at).toLocaleString() : '-' },
          { key: 'elapsed_s', label: 'Duration', render: (r) => r.elapsed_s ? formatDuration(r.elapsed_s) : '-' },
          { key: 'envelopes_trained', label: 'Envelopes' },
          { key: 'sessions_reprocessed', label: 'Reprocessed' },
          { key: 'sessions_failed', label: 'Failed' },
        ]}
        data={history ?? []}
        emptyMessage="No training runs recorded yet"
      />
    </div>
  );
}
