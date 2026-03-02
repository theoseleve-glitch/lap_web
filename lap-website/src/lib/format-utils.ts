/**
 * Shared formatting utilities for telemetry display.
 *
 * All null/undefined/NaN inputs return em dash (—).
 * Numeric precision matches the desktop tool (ground truth).
 */

const EM_DASH = '\u2014';

/** Lap time: sub-60s → "45.123s", 60s+ → "1:02.345" */
export function formatLapTime(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return EM_DASH;
  if (seconds >= 60) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds - mins * 60;
    return `${mins}:${secs.toFixed(3).padStart(6, '0')}`;
  }
  return `${seconds.toFixed(3)}s`;
}

/** Date: ISO "2026-01-15" → "15 Jan 2026" (en-GB) */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return EM_DASH;
  try {
    const d = new Date(dateStr + 'T00:00:00');
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return dateStr;
  }
}

/** Distance in meters, integer precision (matches desktop %.0f) */
export function formatDistance(meters: number | null | undefined): string {
  if (meters == null || !isFinite(meters)) return EM_DASH;
  return String(Math.round(meters));
}

/** Speed: m/s → km/h with 1 decimal (matches desktop %.1f) */
export function mpsToKmh(mps: number | null | undefined): string {
  if (mps == null || !isFinite(mps)) return EM_DASH;
  return (mps * 3.6).toFixed(1);
}

/** Acceleration: m/s² → G with 2 decimals, absolute value (matches desktop %.2f) */
export function mps2ToG(mps2: number | null | undefined): string {
  if (mps2 == null || !isFinite(mps2)) return EM_DASH;
  return (Math.abs(mps2) / 9.81).toFixed(2);
}

/** Score color class based on thresholds */
export function scoreColor(score: number | null): string {
  if (score == null) return 'text-steel';
  if (score >= 80) return 'text-acid-green';
  if (score >= 60) return 'text-marshal-yellow';
  if (score >= 40) return 'text-pit-orange';
  return 'text-safety-red';
}
