'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { api } from '@/lib/api-client';
import { PageHeader } from '@/components/app';

interface SetupStep {
  id: string;
  label: string;
  description: string;
  status: 'complete' | 'in_progress' | 'pending' | 'error';
  link: string;
}

interface SetupStatusResponse {
  steps: Array<{ id: string; status: SetupStep['status'] }>;
}

const defaultSteps: SetupStep[] = [
  {
    id: 'create_account',
    label: 'Create Account',
    description: 'Register your account to start tracking telemetry data.',
    status: 'complete',
    link: '/register',
  },
  {
    id: 'upload_session',
    label: 'Upload First Session',
    description: 'Upload a RaceChrono or RaceBox CSV file for analysis.',
    status: 'pending',
    link: '/app/analyze',
  },
  {
    id: 'configure_tracks',
    label: 'Configure Tracks',
    description: 'Set up your track profiles with layout and corner data.',
    status: 'pending',
    link: '/app/tracks',
  },
  {
    id: 'configure_drivers',
    label: 'Configure Drivers',
    description: 'Create driver profiles to track individual performance.',
    status: 'pending',
    link: '/app/drivers',
  },
  {
    id: 'run_analysis',
    label: 'Run First Analysis',
    description: 'Run the 14-stage pipeline on your session data.',
    status: 'pending',
    link: '/app/analyze',
  },
  {
    id: 'view_dashboard',
    label: 'View Dashboard',
    description: 'Review your telemetry overview and performance stats.',
    status: 'pending',
    link: '/app/dashboard',
  },
  {
    id: 'compare_sessions',
    label: 'Compare Sessions',
    description: 'Compare multiple sessions side-by-side for improvement insights.',
    status: 'pending',
    link: '/app/compare',
  },
  {
    id: 'setup_kart',
    label: 'Set Up Kart Profile',
    description: 'Configure your kart setup for envelope analysis.',
    status: 'pending',
    link: '/app/karts/new',
  },
  {
    id: 'create_strategy',
    label: 'Create Race Strategy',
    description: 'Build a race strategy with pit windows and tyre planning.',
    status: 'pending',
    link: '/app/race-strategy/new',
  },
  {
    id: 'export_data',
    label: 'Export Your Data',
    description: 'Download your telemetry data in CSV, JSON, or Parquet format.',
    status: 'pending',
    link: '/app/exports',
  },
];

function StatusIcon({ status }: { status: SetupStep['status'] }) {
  switch (status) {
    case 'complete':
      return (
        <div className="w-8 h-8 rounded-full bg-acid-green/20 border border-acid-green flex items-center justify-center shrink-0">
          <svg className="w-4 h-4 text-acid-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
      );
    case 'in_progress':
      return (
        <div className="w-8 h-8 rounded-full border-2 border-marshal-yellow flex items-center justify-center shrink-0">
          <div className="w-4 h-4 border-2 border-marshal-yellow/30 border-t-marshal-yellow rounded-full animate-spin" />
        </div>
      );
    case 'error':
      return (
        <div className="w-8 h-8 rounded-full bg-safety-red/20 border border-safety-red flex items-center justify-center shrink-0">
          <svg className="w-4 h-4 text-safety-red" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
      );
    default:
      return (
        <div className="w-8 h-8 rounded-full border border-steel/40 flex items-center justify-center shrink-0">
          <div className="w-3 h-3 rounded-full bg-steel/30" />
        </div>
      );
  }
}

function stepBorderColor(status: SetupStep['status']): string {
  switch (status) {
    case 'complete':
      return 'border-acid-green/30 hover:border-acid-green/60';
    case 'in_progress':
      return 'border-marshal-yellow/30 hover:border-marshal-yellow/60';
    case 'error':
      return 'border-safety-red/30 hover:border-safety-red/60';
    default:
      return 'border-steel/20 hover:border-steel/40';
  }
}

function stepNumber(index: number, status: SetupStep['status']): string {
  if (status === 'complete') return 'text-acid-green';
  if (status === 'in_progress') return 'text-marshal-yellow';
  if (status === 'error') return 'text-safety-red';
  return 'text-steel/60';
}

export default function SetupTrackerPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['setup', 'status'],
    queryFn: () => api.get<SetupStatusResponse>('/setup/status'),
    enabled: true,
  });

  // Merge API status into default steps
  const steps: SetupStep[] = defaultSteps.map((step) => {
    const apiStep = data?.steps?.find((s) => s.id === step.id);
    return apiStep ? { ...step, status: apiStep.status } : step;
  });

  const completedCount = steps.filter((s) => s.status === 'complete').length;
  const totalCount = steps.length;
  const progressPercent = Math.round((completedCount / totalCount) * 100);

  return (
    <div>
      <PageHeader
        title="Setup Tracker"
        subtitle={`${completedCount} of ${totalCount} steps complete`}
      />

      {/* Progress bar */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <div className="flex items-center justify-between mb-3">
          <span className="font-telemetry text-xs uppercase tracking-wider text-steel">
            Platform Setup Progress
          </span>
          <span className="font-telemetry text-sm text-chalk">
            {progressPercent}%
          </span>
        </div>
        <div className="w-full h-3 bg-asphalt rounded-full overflow-hidden">
          <div
            className="h-full bg-acid-green rounded-full transition-all duration-500 ease-out"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="font-body text-xs text-steel">
            {completedCount} complete
          </span>
          <span className="font-body text-xs text-steel">
            {totalCount - completedCount} remaining
          </span>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center justify-center h-24 mb-6">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        </div>
      )}

      {/* Error banner */}
      {error && !isLoading && (
        <div className="bg-safety-red/10 border border-safety-red/30 rounded-lg p-3 mb-6">
          <p className="text-safety-red font-telemetry text-xs">
            Couldn&apos;t load your progress — showing default steps. Refresh to try again.
          </p>
        </div>
      )}

      {/* Steps grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {steps.map((step, index) => (
          <Link
            key={step.id}
            href={step.link}
            className={`block bg-concrete rounded-lg border ${stepBorderColor(step.status)} p-5 transition-all duration-200 hover:bg-concrete/80 group`}
          >
            <div className="flex items-start gap-4">
              <StatusIcon status={step.status} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`font-telemetry text-xs ${stepNumber(index, step.status)}`}>
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <h3 className="font-monument text-lg text-chalk tracking-tight leading-tight group-hover:text-acid-green transition-colors">
                    {step.label}
                  </h3>
                </div>
                <p className="font-body text-sm text-steel leading-relaxed">
                  {step.description}
                </p>
                {step.status === 'complete' && (
                  <span className="inline-block mt-2 font-telemetry text-xs text-acid-green uppercase tracking-wider">
                    Completed
                  </span>
                )}
                {step.status === 'in_progress' && (
                  <span className="inline-block mt-2 font-telemetry text-xs text-marshal-yellow uppercase tracking-wider">
                    In Progress
                  </span>
                )}
                {step.status === 'error' && (
                  <span className="inline-block mt-2 font-telemetry text-xs text-safety-red uppercase tracking-wider">
                    Error — Click to retry
                  </span>
                )}
              </div>
              <svg
                className="w-5 h-5 text-steel/60 group-hover:text-chalk transition-colors shrink-0 mt-1"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
              </svg>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
