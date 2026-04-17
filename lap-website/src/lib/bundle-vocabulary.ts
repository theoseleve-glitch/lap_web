/**
 * The single bridge between backend codes and user-readable labels.
 *
 * Every component that renders tier/readiness/decision information reads
 * from these maps — no hardcoded strings.
 */
import type { SupportLevel } from '@/types/bundles';

// ── Support tier → product language ────────────────────────

export const SUPPORT_LEVELS: Record<string, SupportLevel> = {
  A: {
    tier: 'A',
    label: 'Full Analysis',
    color: 'acid-green',
    plannerModes: ['Standard Strategy', 'Safe Strategy', 'Race Strategy'],
    description: 'All analysis modes available. Highest confidence.',
  },
  B: {
    tier: 'B',
    label: 'Standard Analysis',
    color: 'gold',
    plannerModes: ['Standard Strategy', 'Safe Strategy'],
    description: 'Core analysis available. Race strategy requires more data.',
  },
  C: {
    tier: 'C',
    label: 'Basic Analysis',
    color: 'marshal-yellow',
    plannerModes: [],
    description: 'Lap data and diagnostics only. Strategy modes require better data quality.',
  },
  D: {
    tier: 'D',
    label: 'Not Supported',
    color: 'safety-red',
    plannerModes: [],
    description: 'This session cannot be analyzed. Check the requirements below.',
  },
};

export function getSupportLevel(tier: string | null | undefined): SupportLevel {
  return SUPPORT_LEVELS[tier ?? ''] ?? SUPPORT_LEVELS.D;
}

// ── Readiness reason codes → user text ─────────────────────

export const READINESS_LABELS: Record<string, string> = {
  unknown_sim: 'Simulator not recognized',
  vehicle_spec_incomplete: 'Vehicle data is incomplete',
  vehicle_spec_invalid: 'Vehicle data has invalid values',
  track_spec_incomplete: 'Track information is incomplete',
  track_spec_invalid: 'Track information has invalid values',
  no_telemetry_file: 'No telemetry data file in bundle',
  no_analysis_json: 'No analysis metadata in bundle',
  unsupported_capture_method: 'Capture method not supported',
};

export function getReadinessLabel(code: string): string {
  return READINESS_LABELS[code] ?? code.replace(/_/g, ' ');
}

// ── Release decision → user text ───────────────────────────

export const RELEASE_LABELS: Record<string, { label: string; color: string }> = {
  pass: { label: 'Verified', color: 'acid-green' },
  warn: { label: 'Verified with Warnings', color: 'marshal-yellow' },
  fail: { label: 'Unverified', color: 'safety-red' },
};

// ── Confidence level → user text ───────────────────────────

export const CONFIDENCE_LABELS: Record<string, string> = {
  high: 'High Confidence',
  medium: 'Moderate Confidence',
  low: 'Low Confidence',
  unknown: '',
};

// ── Planner mode → user text ───────────────────────────────

export const PLANNER_MODE_LABELS: Record<string, string> = {
  nominal: 'Standard Strategy',
  robust: 'Safe Strategy',
  exploitable: 'Race Strategy',
};

// ── API error codes → user messages ────────────────────────

export const ERROR_MESSAGES: Record<string, string> = {
  BUNDLE_FILE_MISSING: 'No file selected. Drag a bundle or click to browse.',
  BUNDLE_SIZE_EXCEEDED: 'Bundle exceeds the 500 MB limit.',
  BUNDLE_CONTENT_INVALID: "This file isn't a valid session bundle. Expected a .zip archive.",
  BUNDLE_MANIFEST_MISSING: 'Bundle is missing its manifest file. Re-export from the logger.',
  BUNDLE_MANIFEST_INVALID: 'Bundle manifest is corrupt. Re-export from the logger.',
  BUNDLE_SCHEMA_VERSION_UNSUPPORTED: 'This bundle format is outdated. Update your logger to v2+.',
  BUNDLE_CHECKSUM_MISMATCH: 'Upload integrity check failed. Please try again.',
  BUNDLE_DUPLICATE: 'This session was already uploaded.',
  BUNDLE_INNER_CHECKSUM_MISMATCH: 'A file inside the bundle failed integrity check. Re-export from the logger.',
  READINESS_NOT_MET: 'This bundle cannot be analyzed yet. Missing required data.',
  SUPPORT_TIER_REFUSED: 'This analysis output is not available at the current analysis level.',
  CONFLICT: 'Analysis is already running. Wait for it to finish.',
};

export function getErrorMessage(code: string): string {
  return ERROR_MESSAGES[code] ?? 'An unexpected error occurred.';
}
