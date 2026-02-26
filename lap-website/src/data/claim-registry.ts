export type CapabilityStatus = 'available_now' | 'enterprise_on_request' | 'roadmap';

export interface CapabilityClaim {
  id: string;
  claim: string;
  capability: string;
  status: CapabilityStatus;
  surfaces: string[];
}

export const capabilityClaims: CapabilityClaim[] = [
  {
    id: 'upload_csv_analysis',
    claim: 'Upload RaceChrono-compatible CSV telemetry and receive automated lap analysis.',
    capability: 'Telemetry ingest and analysis pipeline',
    status: 'available_now',
    surfaces: ['home', 'product', 'pricing'],
  },
  {
    id: 'corner_picker',
    claim: 'Corner-level analysis with entry, apex, and exit feedback is available in the product workflow.',
    capability: 'Corner analysis tooling',
    status: 'available_now',
    surfaces: ['product', 'drivers'],
  },
  {
    id: 'session_tabs',
    claim: 'Session intelligence includes Overview, Corners, Timeline, Analytics, and Lap Data tabs.',
    capability: 'Session intelligence workspace',
    status: 'available_now',
    surfaces: ['product'],
  },
  {
    id: 'comparison_modes',
    claim: 'Session-vs-session and driver-vs-driver comparison views are supported.',
    capability: 'Comparison and progress analytics',
    status: 'available_now',
    surfaces: ['product', 'teams'],
  },
  {
    id: 'team_workspace',
    claim: 'Workspace and role-based access controls are available for team plans.',
    capability: 'Account and team management',
    status: 'enterprise_on_request',
    surfaces: ['product', 'teams', 'pricing'],
  },
  {
    id: 'race_strategy',
    claim: 'Race Strategy Control Room dashboards are available for enterprise operators.',
    capability: 'Live race strategy dashboards',
    status: 'enterprise_on_request',
    surfaces: ['product', 'circuits', 'endurance'],
  },
  {
    id: 'data_rights',
    claim: 'Data export, deletion, and retention controls are built into account settings.',
    capability: 'Data rights controls',
    status: 'available_now',
    surfaces: ['product', 'security', 'privacy'],
  },
  {
    id: 'sim_waitlist',
    claim: 'Sim racing ingestion is roadmap only and currently available through waitlist.',
    capability: 'Sim telemetry ingestion',
    status: 'roadmap',
    surfaces: ['waitlist', 'pricing', 'drivers'],
  },
  {
    id: 'webhooks_tiering',
    claim: 'Advanced webhook tiering is a roadmap item and not yet generally available.',
    capability: 'Tiered webhook delivery',
    status: 'roadmap',
    surfaces: ['pricing', 'teams'],
  },
  {
    id: 'audit_traceability',
    claim: 'Pipeline job traceability and audit logs are available for compliance review.',
    capability: 'Auditability and traceability',
    status: 'enterprise_on_request',
    surfaces: ['security', 'status'],
  },
];

export const claimsByStatus = capabilityClaims.reduce<Record<CapabilityStatus, CapabilityClaim[]>>(
  (acc, claim) => {
    acc[claim.status].push(claim);
    return acc;
  },
  {
    available_now: [],
    enterprise_on_request: [],
    roadmap: [],
  },
);

export function getClaimsForSurface(surface: string): CapabilityClaim[] {
  return capabilityClaims.filter((claim) => claim.surfaces.includes(surface));
}
