const DEFAULT_SITE_ORIGIN = 'https://lap.racing';

const ALLOWED_HOSTS = new Set([
  'lap.racing',
  'www.lap.racing',
  'lap-coach.racing',
  'www.lap-coach.racing',
  'localhost',
  '127.0.0.1',
]);

function parseUrl(value: string | undefined): URL | null {
  if (!value) return null;
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function isAllowedOrigin(url: URL): boolean {
  if (!ALLOWED_HOSTS.has(url.hostname)) {
    return false;
  }

  if (url.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(url.hostname)) {
    return false;
  }

  return url.protocol === 'https:' || url.protocol === 'http:';
}

export function getValidatedSiteOrigin(): string {
  const configuredUrl =
    parseUrl(process.env.NEXT_PUBLIC_SITE_URL) ?? parseUrl(process.env.SITE_URL) ?? parseUrl(DEFAULT_SITE_ORIGIN);

  if (!configuredUrl || !isAllowedOrigin(configuredUrl)) {
    return DEFAULT_SITE_ORIGIN;
  }

  return configuredUrl.origin;
}

