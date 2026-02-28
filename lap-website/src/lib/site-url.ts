const DEFAULT_SITE_URL = 'https://www.lap-coach.racing';

function normalizeSiteUrl(value: string): string {
  let parsed: URL;

  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`SITE_URL must be a valid absolute URL. Received: ${value}`);
  }

  if (parsed.protocol !== 'https:') {
    throw new Error(`SITE_URL must use https protocol. Received: ${value}`);
  }

  if (parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== '/') {
    throw new Error(
      `SITE_URL must not include credentials, path, query, or hash. Received: ${value}`,
    );
  }

  return parsed.origin;
}

export function getSiteUrl(envValue: string | undefined = process.env.SITE_URL): string {
  const trimmed = envValue?.trim();

  if (!trimmed) {
    return DEFAULT_SITE_URL;
  }

  return normalizeSiteUrl(trimmed);
}

export function getSiteUrlAsUrl(envValue: string | undefined = process.env.SITE_URL): URL {
  return new URL(getSiteUrl(envValue));
}

export function getSiteHostname(envValue: string | undefined = process.env.SITE_URL): string {
  return getSiteUrlAsUrl(envValue).hostname;
}

export { DEFAULT_SITE_URL };
