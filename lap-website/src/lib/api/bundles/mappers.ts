/**
 * Transport DTO → Presentation DTO mappers.
 *
 * Rules:
 *   - Preserve explicit null / missing values
 *   - Map enums into display-safe discriminated unions
 *   - Do NOT infer canonical IDs
 *   - Do NOT default missing values to zero
 *   - Do NOT hide blocking reasons or warnings
 */
import type {
  AnalysisRunDTO,
  ArtifactPresentation,
  ArtifactState,
  BundleArtifactRefDTO,
  BundleOverviewDTO,
  ReadinessState,
  ResolutionState,
  RunLifecycle,
  RunPresentation,
  SessionPresentation,
  SupportTier,
} from './types';

// ── Resolution ────────────────────────────────────────────

export function mapResolution(overview: BundleOverviewDTO): ResolutionState {
  // Unresolved if vehicle or track name is missing/empty
  if (!overview.vehicle_name && !overview.vehicle_key) return 'unresolved';
  if (!overview.track_name && !overview.track_key) return 'unresolved';
  return 'resolved';
}

// ── Readiness ─────────────────────────────────────────────

export function mapReadiness(overview: BundleOverviewDTO): ReadinessState {
  if (overview.readiness.is_ready) return 'ready';
  // "blocked" = has blocking reasons; "degraded" = accepted but limited
  if (overview.readiness.reasons.length > 0) return 'blocked';
  return 'degraded';
}

// ── Support tier ──────────────────────────────────────────

const TIER_MAP: Record<string, SupportTier> = {
  A: 'full',
  B: 'standard',
  C: 'limited',
  D: 'limited',
};

const TIER_LABELS: Record<SupportTier, string> = {
  full: 'Full Analysis',
  standard: 'Standard Analysis',
  limited: 'Limited Analysis',
};

const TIER_COLORS: Record<SupportTier, string> = {
  full: 'acid-green',
  standard: 'gold',
  limited: 'marshal-yellow',
};

export function mapSupportTier(raw: string | null): SupportTier | null {
  if (!raw) return null;
  return TIER_MAP[raw] ?? 'limited';
}

export function getTierLabel(tier: SupportTier | null): string {
  return tier ? TIER_LABELS[tier] : 'Not Analyzed';
}

export function getTierColor(tier: SupportTier | null): string {
  return tier ? TIER_COLORS[tier] : 'steel';
}

// ── Run lifecycle ─────────────────────────────────────────

export function mapRunLifecycle(run: AnalysisRunDTO | null): RunLifecycle | null {
  if (!run) return null;
  switch (run.status) {
    case 'queued':
    case 'running':
      return 'validated';
    case 'succeeded':
      return 'analyzed';
    case 'failed':
      return 'failed';
    default:
      return 'uploaded';
  }
}

// ── Confidence + release labels ───────────────────────────

const CONFIDENCE_LABELS: Record<string, string> = {
  high: 'High Confidence',
  medium: 'Moderate Confidence',
  low: 'Low Confidence',
  unknown: '',
};

const RELEASE_MAP: Record<string, { label: string; color: string }> = {
  pass: { label: 'Verified', color: 'acid-green' },
  warn: { label: 'Verified with Warnings', color: 'marshal-yellow' },
  fail: { label: 'Unverified', color: 'safety-red' },
};

// ── Artifact state ────────────────────────────────────────

export function mapArtifactState(
  artifact: BundleArtifactRefDTO,
  run: AnalysisRunDTO | null,
  availableKinds: string[],
): ArtifactState {
  if (!run) return 'pending';
  if (run.status === 'queued' || run.status === 'running') return 'pending';
  if (!availableKinds.includes(artifact.role)) return 'gated';
  return 'available';
}

export function getArtifactGateReason(
  artifact: BundleArtifactRefDTO,
  state: ArtifactState,
  run: AnalysisRunDTO | null,
): string | null {
  if (state === 'gated') {
    const tier = run?.support_tier ?? 'D';
    return `Requires a higher analysis level (current: ${TIER_MAP[tier] ?? 'limited'})`;
  }
  if (state === 'pending') return 'Analysis in progress';
  if (state === 'unavailable') return 'Not available for this session';
  return null;
}

// ── Planner modes ─────────────────────────────────────────

const MODE_LABELS: Record<string, string> = {
  nominal: 'Standard Strategy',
  robust: 'Safe Strategy',
  exploitable: 'Race Strategy',
};

// ── Composite mappers ─────────────────────────────────────

export function mapSessionPresentation(dto: BundleOverviewDTO): SessionPresentation {
  return {
    bundleId: dto.bundle_id,
    sim: dto.sim,
    vehicleName: dto.vehicle_name || null,
    trackName: dto.track_name || null,
    sessionType: dto.session_type,
    startedAt: dto.started_at,
    lapCount: dto.lap_count,
    durationS: dto.duration_s,
    uploadedAt: dto.uploaded_at,
    resolution: mapResolution(dto),
    readiness: mapReadiness(dto),
    blockingReasons: dto.readiness.reasons,
    warnings: [],
    degradedFields: dto.readiness.degraded_fields,
    supportTier: null,   // set from run data
    runLifecycle: null,  // set from run data
    latestRunId: dto.latest_run_id,
  };
}

export function mapRunPresentation(dto: AnalysisRunDTO): RunPresentation {
  const tier = mapSupportTier(dto.support_tier);
  const release = dto.release_decision ? RELEASE_MAP[dto.release_decision] : null;

  const modes = ['nominal', 'robust', 'exploitable'].map((key) => ({
    name: MODE_LABELS[key] ?? key,
    available: dto.planner_mode_availability?.[key as keyof typeof dto.planner_mode_availability] ?? false,
  }));

  return {
    runId: dto.run_id,
    lifecycle: mapRunLifecycle(dto)!,
    supportTier: tier,
    tierLabel: getTierLabel(tier),
    tierColor: getTierColor(tier),
    confidenceLabel: CONFIDENCE_LABELS[dto.confidence_level ?? ''] ?? '',
    releaseLabel: release?.label ?? null,
    releaseColor: release?.color ?? null,
    warnings: dto.warnings ?? [],
    errorCode: dto.error_code,
    errorMessage: dto.error_message,
    plannerModes: modes,
    createdAt: dto.created_at,
    completedAt: dto.completed_at,
  };
}

export function mapArtifactPresentation(
  dto: BundleArtifactRefDTO,
  run: AnalysisRunDTO | null,
  availableKinds: string[],
): ArtifactPresentation {
  const state = mapArtifactState(dto, run, availableKinds);
  return {
    role: dto.role,
    state,
    sizeBytes: dto.size_bytes,
    downloadUrl: state === 'available' ? dto.download_url : null,
    gateReason: getArtifactGateReason(dto, state, run),
  };
}
