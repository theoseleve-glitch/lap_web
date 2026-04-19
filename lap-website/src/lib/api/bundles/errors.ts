/** Error code → user-facing message mapping for bundle operations. */

const ERROR_MESSAGES: Record<string, string> = {
  BUNDLE_FILE_MISSING: 'No file selected. Drag a bundle or click to browse.',
  BUNDLE_SIZE_EXCEEDED: 'Bundle exceeds the 500 MB limit.',
  BUNDLE_CONTENT_INVALID: "This file isn't a valid session bundle. Expected a .zip archive.",
  BUNDLE_MANIFEST_MISSING: 'Bundle is missing its manifest file. Re-export from the logger.',
  BUNDLE_MANIFEST_INVALID: 'Bundle manifest is corrupt. Re-export from the logger.',
  BUNDLE_SCHEMA_VERSION_UNSUPPORTED: 'This bundle format is outdated. Update your logger to v2+.',
  BUNDLE_CHECKSUM_MISMATCH: 'Upload integrity check failed. Please try again.',
  BUNDLE_DUPLICATE: 'This session was already uploaded.',
  BUNDLE_INNER_CHECKSUM_MISMATCH: 'A file inside the bundle failed integrity check.',
  READINESS_NOT_MET: 'This bundle cannot be analyzed yet. Missing required data.',
  SUPPORT_TIER_REFUSED: 'This output is not available at the current analysis level.',
  CONFLICT: 'Analysis is already running.',
  NOT_FOUND: 'Session not found.',
};

export function getErrorMessage(code: string | null | undefined): string {
  if (!code) return 'An unexpected error occurred.';
  return ERROR_MESSAGES[code] ?? `Error: ${code.replace(/_/g, ' ').toLowerCase()}`;
}
