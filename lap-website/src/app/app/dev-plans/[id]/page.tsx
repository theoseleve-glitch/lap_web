'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader, StatCard, QueryError, SkeletonStatCards, SkeletonBox } from '@/components/app';

interface Task {
  id: number;
  title: string;
  status: 'pending' | 'in_progress' | 'completed';
  assignee: string | null;
  notes: string | null;
}

interface DevPlanDetail {
  id: number;
  title: string;
  description: string;
  status: string;
  priority: string;
  created_at: string;
  updated_at: string;
  progress_pct: number;
  tasks: Task[];
}

const taskStatusIcons: Record<string, string> = {
  pending: '○',
  in_progress: '◎',
  completed: '●',
};

const taskStatusColors: Record<string, string> = {
  pending: 'text-steel',
  in_progress: 'text-acid-green',
  completed: 'text-marshal-yellow',
};

export default function DevPlanDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data: plan, isLoading, error } = useQuery({
    queryKey: ['dev-plan', id],
    queryFn: () => api.get<DevPlanDetail>(`/dev-plans/${id}`),
  });

  if (isLoading) {
    return (
      <div>
        <div className="mb-4">
          <SkeletonBox className="h-6 w-48 mb-2" />
          <SkeletonBox className="h-3 w-32" />
        </div>
        <SkeletonStatCards count={4} />
        <SkeletonBox className="h-32 w-full mt-6 rounded-lg" />
      </div>
    );
  }

  if (error) {
    return <QueryError message="Couldn't load plan details." onRetry={() => window.location.reload()} />;
  }

  if (!plan) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/20 p-12 text-center">
        <h2 className="font-monument text-lg text-chalk mb-2">Plan not found</h2>
        <p className="text-steel font-body text-sm mb-4">This plan may have been deleted or the link is invalid.</p>
        <Link href="/app/dev-plans" className="text-pit-orange font-telemetry text-xs hover:underline">
          Back to plans
        </Link>
      </div>
    );
  }

  const completedTasks = plan.tasks.filter((t) => t.status === 'completed').length;

  return (
    <div>
      <PageHeader
        title={plan.title}
        subtitle={`${plan.priority} priority · ${plan.status}`}
        actions={
          <Link
            href="/app/dev-plans"
            className="px-3 py-1.5 border border-steel/30 text-steel font-telemetry text-xs rounded hover:text-chalk transition-colors"
          >
            All Plans
          </Link>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Progress" value={`${plan.progress_pct}%`} />
        <StatCard label="Tasks" value={`${completedTasks}/${plan.tasks.length}`} />
        <StatCard label="Created" value={plan.created_at} />
        <StatCard label="Updated" value={plan.updated_at} />
      </div>

      {/* Description */}
      {plan.description && (
        <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
          <h3 className="font-body text-chalk text-sm mb-2">Description</h3>
          <p className="text-steel font-body text-sm whitespace-pre-wrap">{plan.description}</p>
        </div>
      )}

      {/* Progress bar */}
      <div className="mb-6">
        <div className="flex justify-between mb-1">
          <span className="font-telemetry text-xs text-steel">Overall Progress</span>
          <span className="font-telemetry text-xs text-acid-green">{plan.progress_pct}%</span>
        </div>
        <div className="w-full bg-steel/20 rounded-full h-2">
          <div
            className="bg-acid-green h-2 rounded-full transition-all"
            style={{ width: `${plan.progress_pct}%` }}
          />
        </div>
      </div>

      {/* Task list */}
      <div className="bg-concrete rounded-lg border border-steel/20 overflow-hidden">
        <div className="px-4 py-3 border-b border-steel/20">
          <h3 className="font-body text-chalk text-sm">Tasks</h3>
        </div>
        {plan.tasks.length === 0 ? (
          <div className="p-4 text-center text-steel font-body text-sm">No tasks yet.</div>
        ) : (
          <div className="divide-y divide-steel/10">
            {plan.tasks.map((task) => (
              <div key={task.id} className="px-4 py-3 flex items-start gap-3">
                <span
                  className={`mt-0.5 font-telemetry ${taskStatusColors[task.status] ?? 'text-steel'}`}
                >
                  {taskStatusIcons[task.status] ?? '○'}
                </span>
                <div className="flex-1">
                  <div
                    className={`font-body text-sm ${
                      task.status === 'completed'
                        ? 'text-steel line-through'
                        : 'text-chalk'
                    }`}
                  >
                    {task.title}
                  </div>
                  {task.assignee && (
                    <span className="text-xs font-telemetry text-steel">{task.assignee}</span>
                  )}
                  {task.notes && (
                    <p className="text-xs text-steel/70 mt-1">{task.notes}</p>
                  )}
                </div>
                <span
                  className={`font-telemetry text-xs uppercase ${taskStatusColors[task.status] ?? 'text-steel'}`}
                >
                  {task.status.replace('_', ' ')}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
