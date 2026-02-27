const previewBaseUrl = process.env.PREVIEW_URL || 'http://127.0.0.1:3000';

function parseSitemapUrls(xml) {
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1].trim());
}

function isAuthRoute(pathname) {
  return ['/login', '/register', '/verify-email', '/oauth-callback'].some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
}

async function main() {
  const sitemapUrl = new URL('/sitemap.xml', previewBaseUrl).toString();
  const sitemapResponse = await fetch(sitemapUrl, { redirect: 'manual' });

  if (!sitemapResponse.ok) {
    throw new Error(`Unable to load sitemap from ${sitemapUrl}: ${sitemapResponse.status}`);
  }

  const sitemapXml = await sitemapResponse.text();
  const sitemapEntries = parseSitemapUrls(sitemapXml);

  if (sitemapEntries.length === 0) {
    throw new Error(`No sitemap entries found at ${sitemapUrl}`);
  }

  const failures = [];

  for (const entry of sitemapEntries) {
    const entryUrl = new URL(entry);
    if (isAuthRoute(entryUrl.pathname)) {
      continue;
    }

    const previewRouteUrl = new URL(entryUrl.pathname, previewBaseUrl).toString();
    const response = await fetch(previewRouteUrl, { redirect: 'manual' });
    if (response.status !== 200 && response.status !== 301) {
      failures.push(`${entryUrl.pathname} -> ${response.status}`);
    }
  }

  if (failures.length > 0) {
    throw new Error(`Sitemap preview check failed:\n${failures.map((failure) => `- ${failure}`).join('\n')}`);
  }

  console.log(`Sitemap preview check passed for ${sitemapEntries.length} URLs (${previewBaseUrl}).`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
