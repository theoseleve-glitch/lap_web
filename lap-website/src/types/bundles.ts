/** Backend envelope shapes for the bundle intake + analysis API. */

export interface ReadinessSummary {
  is_ready: boolean;
  reasons: string[];
  degraded_fields: string[];
}

export interface IntakeResult {
  bundle_id: string;
  status: 'accepted' | 'degraded' | 'rejected';
  schema_version: number;
  checksum_sha256: string;
  size_bytes: number;
  identity_fingerprint: string;
  readiness: ReadinessSummary;
  intake_reasons: string[];
  self_url: string;
  analyze_url: string | null;
  duplicate_of: string | null;
}

export interface BundleOverview {
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
  readiness: ReadinessSummary;
  latest_run_id: string | null;
  uploaded_at: string;
}

export interface BundleListResponse {
  bundles: BundleOverview[];
  count: number;
}

export interface BundleArtifactRef {
  role: string;
  path: string;
  size_bytes: number;
  checksum_sha256: string;
  download_url: string;
}

export interface BundleArtifactIndex {
  bundle_id: string;
  artifacts: BundleArtifactRef[];
}

export interface AnalysisRunSummary {
  run_id: string;
  bundle_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  support_tier: 'A' | 'B' | 'C' | 'D' | null;
  support_reason: string | null;
  confidence_level: 'high' | 'medium' | 'low' | 'unknown' | null;
  release_decision: 'pass' | 'warn' | 'fail' | null;
  created_at: string;
  completed_at: string | null;
}

export interface AnalyzeResponse {
  bundle_id: string;
  run_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  analyze_url: string;
}

/** Frontend-enriched types */

export type UploadPhase = 'idle' | 'dragover' | 'uploading' | 'processing' | 'done' | 'error';

export type UploadState =
  | { phase: 'idle' }
  | { phase: 'dragover' }
  | { phase: 'uploading'; progress: number }
  | { phase: 'processing' }
  | { phase: 'done'; result: IntakeResult }
  | { phase: 'error'; message: string; code?: string; existingBundleId?: string };

export type RunDisplayState =
  | { phase: 'no-run' }
  | { phase: 'queued' }
  | { phase: 'running' }
  | { phase: 'succeeded'; tier: SupportLevel; run: AnalysisRunSummary }
  | { phase: 'failed'; errorMessage: string; run: AnalysisRunSummary };

export interface SupportLevel {
  tier: 'A' | 'B' | 'C' | 'D';
  label: string;
  color: string;
  plannerModes: string[];
  description: string;
}
