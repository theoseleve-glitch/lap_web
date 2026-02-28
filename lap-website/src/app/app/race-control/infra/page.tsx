'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '@/lib/admin-api';
import { MetricCard } from '@/components/admin/MetricCard';
import { ActionButton } from '@/components/admin/ActionButton';

export default function InfraPage() {
  const queryClient = useQueryClient();

  const { data: storage } = useQuery({
    queryKey: ['admin-infra-storage'],
    queryFn: adminApi.storage,
  });

  const { data: maintenance } = useQuery({
    queryKey: ['admin-infra-maintenance'],
    queryFn: adminApi.maintenanceStatus,
    refetchInterval: 15000,
  });

  const toggleMutation = useMutation({
    mutationFn: (params: { enabled: boolean; message: string; reason: string }) =>
      adminApi.toggleMaintenance(params.enabled, params.message, params.reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-infra-maintenance'] });
    },
  });

  const isInMaintenance = maintenance?.enabled === true;

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold text-chalk">Infrastructure</h1>

      {/* Maintenance mode */}
      <div className="mb-6 rounded-lg border border-white/10 bg-concrete p-4">
        <h2 className="mb-2 text-sm font-semibold text-steel">Maintenance Mode</h2>
        <div className="flex items-center gap-4">
          <span className={`text-sm font-medium ${isInMaintenance ? 'text-orange-400' : 'text-green-400'}`}>
            {isInMaintenance ? `ACTIVE — ${maintenance?.message ?? ''}` : 'OFF'}
          </span>
          {isInMaintenance ? (
            <ActionButton
              label="Disable Maintenance"
              variant="primary"
              onConfirm={async (reason) => {
                await toggleMutation.mutateAsync({ enabled: false, message: '', reason });
              }}
            />
          ) : (
            <ActionButton
              label="Enable Maintenance"
              variant="danger"
              onConfirm={async (reason) => {
                await toggleMutation.mutateAsync({
                  enabled: true,
                  message: 'Scheduled maintenance in progress.',
                  reason,
                });
              }}
            />
          )}
        </div>
      </div>

      {/* Storage */}
      {storage && (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-steel">Storage</h2>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <MetricCard
              label="Database Size"
              value={formatBytes(storage.db_size_bytes)}
            />
            {storage.table_count != null && (
              <MetricCard label="Tables" value={storage.table_count} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}
