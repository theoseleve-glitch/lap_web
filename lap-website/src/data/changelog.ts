export interface ChangelogEntry {
  version: string;
  date: string;
  tags: ('feature' | 'fix' | 'improvement' | 'security' | 'breaking')[];
  summary: string;
  details?: string[];
}

export const changelog: ChangelogEntry[] = [
  {
    version: '1.4.0',
    date: '2026-03-05',
    tags: ['feature'],
    summary: 'Corner coaching with cause-ranked delta maps',
    details: [
      'Identify braking, turn-in, and throttle deltas per corner',
      'Ranked coaching suggestions based on time-loss magnitude',
      'New corner overlay in GPS trace view',
    ],
  },
  {
    version: '1.3.0',
    date: '2026-02-28',
    tags: ['feature', 'improvement'],
    summary: 'Multi-session comparison and cross-chart hover sync',
    details: [
      'Compare up to 4 sessions side-by-side',
      'Distance-based hover sync across speed, GPS, and G-G charts',
      'Improved lap-time delta visualization',
    ],
  },
  {
    version: '1.2.1',
    date: '2026-02-20',
    tags: ['fix', 'security'],
    summary: 'Security audit fixes and auth hardening',
    details: [
      'Refresh tokens moved to httpOnly cookies',
      'Security headers added to API and frontend',
      'Upload content validation strengthened',
    ],
  },
  {
    version: '1.2.0',
    date: '2026-02-14',
    tags: ['feature'],
    summary: 'Workspace isolation and team management',
    details: [
      'Multi-tenant workspace support with RLS',
      'Team invitations with role-based access control',
      'Personal workspace auto-created on registration',
    ],
  },
  {
    version: '1.1.0',
    date: '2026-02-01',
    tags: ['feature'],
    summary: 'Streaming ingest pipeline for large files',
    details: [
      'Process 10GB+ files with under 1GB peak memory',
      'Chunked Parquet caching with resume support',
      'Adaptive chunk sizing based on column count',
    ],
  },
  {
    version: '1.0.0',
    date: '2026-01-15',
    tags: ['feature'],
    summary: 'Initial release: 14-stage telemetry pipeline',
    details: [
      'RaceChrono and RaceBox CSV ingestion',
      'Automatic track detection and corner identification',
      'Pace, Consistency, Execution, and Robustness scoring',
      'Speed trace, GPS trace, and G-G diagram visualizations',
    ],
  },
];
