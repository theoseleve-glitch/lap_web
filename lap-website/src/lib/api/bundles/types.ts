/**
 * v2 contract-aligned types for bundle/session analysis.
 *
 * Transport DTOs match the backend Pydantic schemas 1:1.
 * Presentation DTOs are discriminated unions for UI state rendering.
 *
 * Rule: missing or null fields surface as degraded state, never defaulted.
 */

// ── Transport DTOs (from backend) ─────────────────────────

export interface ReadinessSummaryDTO {
  is_ready: boolean;
  reasons: string[];
  degraded_fields: string[];
}

export interface PlannerModeAvailabilityDTO {
  nominal: boolean;
  robust: boolean;
  exploitable: boolean;
}

export interface BundleOverviewDTO {
  bundle_id: string;
  sim: string;
  vehicle_name: string;
  vehicle_key: string;
  track_name: string;
  track_key: string;
  track_regime: string;
  session_type: string;
  started_at: string;
  lap_count: number;
  duration_s: number;
  status: 'accepted' | 'degraded';
  readiness: ReadinessSummaryDTO;
  latest_run_id: string | null;
  uploaded_at: string;
}

export interface BundleListDTO {
  bundles: BundleOverviewDTO[];
  count: number;
}

export interface IntakeResultDTO {
  bundle_id: string;
  status: 'accepted' | 'degraded' | 'rejected';
  schema_version: number;
  checksum_sha256: string;
  size_bytes: number;
  identity_fingerprint: string;
  readiness: ReadinessSummaryDTO;
  intake_reasons: string[];
  self_url: string;
  analyze_url: string | null;
  duplicate_of: string | null;
}

export interface AnalysisRunDTO {
  run_id: string;
  bundle_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  support_tier: 'A' | 'B' | 'C' | 'D' | null;
  support_reason: string | null;
  confidence_level: 'high' | 'medium' | 'low' | 'unknown' | null;
  fallback_depth_pct: Record<string, number> | null;
  validated_vehicle_profile: string | null;
  validated_track_profile: string | null;
  planner_mode_availability: PlannerModeAvailabilityDTO | null;
  warnings: string[];
  artifacts_available: string[];
  release_decision: 'pass' | 'warn' | 'fail' | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface BundleArtifactRefDTO {
  role: string;
  path: string;
  size_bytes: number;
  checksum_sha256: string;
  download_url: string;
}

export interface BundleArtifactIndexDTO {
  bundle_id: string;
  artifacts: BundleArtifactRefDTO[];
}

export interface AnalyzeResponseDTO {
  bundle_id: string;
  run_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  analyze_url: string;
}

// ── Presentation types (discriminated unions) ─────────────

export type ResolutionState = 'resolved' | 'unresolved';
export type ReadinessState = 'ready' | 'degraded' | 'blocked';
export type SupportTier = 'full' | 'standard' | 'limited';
export type ArtifactState = 'available' | 'unavailable' | 'gated' | 'pending';
export type RunLifecycle = 'uploaded' | 'validated' | 'analyzed' | 'failed';

export interface SessionPresentation {
  bundleId: string;
  sim: string;
  vehicleName: string | null;
  trackName: string | null;
  sessionType: string;
  startedAt: string;
  lapCount: number;
  durationS: number;
  uploadedAt: string;
  resolution: ResolutionState;
  readiness: ReadinessState;
  blockingReasons: string[];
  warnings: string[];
  degradedFields: string[];
  supportTier: SupportTier | null;
  runLifecycle: RunLifecycle | null;
  latestRunId: string | null;
}

export interface ArtifactPresentation {
  role: string;
  state: ArtifactState;
  sizeBytes: number;
  downloadUrl: string | null;
  gateReason: string | null;
}

export interface RunPresentation {
  runId: string;
  lifecycle: RunLifecycle;
  supportTier: SupportTier | null;
  tierLabel: string;
  tierColor: string;
  confidenceLabel: string;
  releaseLabel: string | null;
  releaseColor: string | null;
  warnings: string[];
  errorCode: string | null;
  errorMessage: string | null;
  plannerModes: { name: string; available: boolean }[];
  createdAt: string;
  completedAt: string | null;
}
