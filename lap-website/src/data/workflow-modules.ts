import type { CapabilityStatus } from '@/data/claim-registry';

export interface WorkflowModule {
  id: string;
  title: string;
  summary: string;
  steps: string[];
  status: CapabilityStatus;
  group: 'coaching' | 'strategy';
}

export const workflowModules: WorkflowModule[] = [
  {
    id: 'session-intelligence',
    title: 'Session Intelligence',
    summary: 'Review each session through dedicated intelligence tabs.',
    steps: ['Overview', 'Corners', 'Timeline', 'Analytics', 'Lap Data'],
    status: 'available_now',
    group: 'coaching',
  },
  {
    id: 'comparison-progress',
    title: 'Comparison and Progress',
    summary: 'Track performance deltas across sessions and drivers.',
    steps: [
      'Session-vs-session deltas',
      'Driver-vs-driver overlays',
      'Leaderboard and progression history',
    ],
    status: 'available_now',
    group: 'coaching',
  },
  {
    id: 'coaching-plans',
    title: 'Coaching Plans',
    summary: 'Link drills to observed issues and monitor completion.',
    steps: [
      'Drill recommendations by corner',
      'Assigned practice plans',
      'Progress scoring and notes',
    ],
    status: 'coming_soon',
    group: 'coaching',
  },
  {
    id: 'visualization-workspace',
    title: 'Visualization Workspace',
    summary: 'Explore map, speed, and G-G signals in synchronized layouts.',
    steps: [
      'Track map replay',
      'Speed graph and braking traces',
      'G-G diagram and outlier review',
      'Multi-session comparison mode',
    ],
    status: 'available_now',
    group: 'coaching',
  },
  {
    id: 'ai-lap-optimizer',
    title: 'AI Lap Time Optimizer',
    summary: 'Use AI models to find the optimal racing line and lap time.',
    steps: [
      'Optimal line computation',
      'Braking and throttle suggestions',
      'Sector-by-sector improvement targets',
    ],
    status: 'coming_soon',
    group: 'coaching',
  },
  {
    id: 'strategy-control-room',
    title: 'Race Strategy Control Room',
    summary: 'Use live dashboards for event operations and race planning.',
    steps: [
      'Live pace and stint monitoring',
      'Pit stop planning board',
      'Incident and alert queue',
      'Session feed health diagnostics',
    ],
    status: 'available_now',
    group: 'strategy',
  },
  {
    id: 'live-timing-api',
    title: 'Live Timing API Integration',
    summary: 'Connect to live timing feeds for real-time position and gap data.',
    steps: [
      'Live timing data ingestion',
      'Real-time gap and interval tracking',
      'Position change alerts',
    ],
    status: 'coming_soon',
    group: 'strategy',
  },
  {
    id: 'meteo-radar',
    title: 'Meteo Radar',
    summary: 'Track weather conditions and forecasts to inform strategy calls.',
    steps: [
      'Live weather overlay on track map',
      'Rain probability timeline',
      'Tire strategy recommendations',
    ],
    status: 'coming_soon',
    group: 'strategy',
  },
  {
    id: 'dynamic-strategy',
    title: 'Dynamic Strategy',
    summary: 'Adaptive race strategy that recalculates based on live conditions.',
    steps: [
      'Real-time pit window recalculation',
      'Fuel and tire degradation modeling',
      'Scenario simulation and what-if analysis',
    ],
    status: 'coming_soon',
    group: 'strategy',
  },
];
