const DEFAULT_FALLBACK = '/app/dashboard';

/** True if `value` contains a C0 control character (codes 0-31) or DEL (127). */
function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code <= 31 || code === 127) return true;
  }
  return false;
}

/**
 * Rejects anything that isn't a same-origin relative path: absolute URLs
 * (`https://evil.example`), protocol-relative URLs (`//evil.example`),
 * backslash tricks some browsers normalize into protocol-relative URLs
 * (`/\evil.example`), embedded schemes (`javascript:alert(1)`), and control
 * characters.
 */
function isUnsafePath(value: string): boolean {
  if (!value.startsWith('/')) return true;
  if (value.startsWith('//')) return true;
  if (value.startsWith('/\\')) return true;
  if (value.includes('\\')) return true;
  if (value.includes('://')) return true;
  if (hasControlChar(value)) return true;
  return false;
}

/**
 * Validates a `redirect` query param (or similar user-supplied target) as a
 * safe, same-origin relative path before it is ever handed to `router.push`.
 *
 * Returns `raw` unchanged only if it is a same-origin relative path; returns
 * `fallback` for anything else, including absolute URLs, protocol-relative
 * URLs (`//evil.example`), embedded schemes (`javascript:...`), and
 * percent-encoded tricks that decode into one of the above
 * (e.g. `/%2f%2fevil.example`).
 */
export function getSafeRedirect(
  raw: string | null | undefined,
  fallback: string = DEFAULT_FALLBACK,
): string {
  if (!raw) return fallback;

  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    return fallback;
  }

  if (isUnsafePath(raw) || isUnsafePath(decoded)) {
    return fallback;
  }

  return raw;
}
