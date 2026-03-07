import type { CapabilityStatus } from '@/data/claim-registry';

export interface WorkflowModule {
  id: string;
  title: string;
  summary: string;
  steps: string[];
  status: CapabilityStatus;
  group: 'coaching' | 'strategy' | 'operations';
}

export const workflowModules: WorkflowModule[] = [
  {
    id: 'upload-analyze',
    title: 'Upload and Analyze',
    summary: 'Move from raw file to validated analysis with explicit operator checks.',
    steps: [
      'File select and format validation',
      'Session metadata capture',
      'Corner picker and segment review',
      'Joker confirmation before final scoring',
    ],
    status: 'available_now',
    group: 'coaching',
  },
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
    status: 'available_now',
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
    id: 'data-management',
    title: 'Data Management',
    summary: 'Maintain clean entities for tracks, karts, drivers, and weekends.',
    steps: [
      'Track library and layout management',
      'Kart profiles and setup records',
      'Driver roster and availability',
      'Weekend event grouping',
    ],
    status: 'available_now',
    group: 'operations',
  },
  {
    id: 'account-team',
    title: 'Account and Team',
    summary: 'Manage identities, OAuth providers, and role-based access.',
    steps: [
      'Email auth and OAuth login',
      'Workspace and team setup',
      'Role and permission controls',
    ],
    status: 'enterprise_on_request',
    group: 'operations',
  },
  {
    id: 'data-rights',
    title: 'Data Rights',
    summary: 'Control data lifecycle and user rights workflows.',
    steps: [
      'Self-serve export requests',
      'Deletion requests and processing',
      'Retention policy controls',
    ],
    status: 'available_now',
    group: 'operations',
  },
];
