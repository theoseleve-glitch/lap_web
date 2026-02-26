import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const srcDir = path.join(root, 'src');
const appDir = path.join(srcDir, 'app');
const claimFile = path.join(srcDir, 'data', 'claim-registry.ts');

function walk(dir, predicate) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const results = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walk(fullPath, predicate));
    } else if (!predicate || predicate(fullPath)) {
      results.push(fullPath);
    }
  }
  return results;
}

function read(filePath) {
  return fs.readFileSync(filePath, 'utf8');
}

function normalizeRoute(route) {
  if (!route) return '/';
  const cleaned = route.endsWith('/') && route !== '/' ? route.slice(0, -1) : route;
  return cleaned || '/';
}

function stripRouteGroups(route) {
  return route.replace(/\/\([^/]+\)/g, '');
}

function collectRoutes() {
  const pages = walk(appDir, (filePath) => filePath.endsWith('page.tsx'));
  return pages.map((pagePath) => {
    const relative = path.relative(appDir, pagePath).replace(/\\/g, '/');
    const withoutPage = relative.replace(/\/page\.tsx$/, '').replace(/^page\.tsx$/, '');
    const route = stripRouteGroups(`/${withoutPage}`);
    return normalizeRoute(route);
  });
}

function buildRouteMatchers(routes) {
  return routes.map((route) => {
    if (!route.includes('[')) {
      return { route, regex: new RegExp(`^${route.replace(/\//g, '\\/')}$`) };
    }
    const dynamic = route.replace(/\[[^/]+\]/g, '[^/]+');
    return { route, regex: new RegExp(`^${dynamic.replace(/\//g, '\\/')}$`) };
  });
}

function collectInternalHrefs() {
  const files = walk(srcDir, (filePath) => /\.(ts|tsx)$/.test(filePath));
  const hrefRegex = /href=["'`](\/[^"'`]+)["'`]/g;
  const results = [];

  for (const filePath of files) {
    const content = read(filePath);
    let match;
    while ((match = hrefRegex.exec(content)) !== null) {
      const raw = match[1];
      if (raw.startsWith('/api/')) continue;
      const [pathPart] = raw.split(/[?#]/);
      results.push({
        filePath,
        href: normalizeRoute(pathPart),
      });
    }
  }

  return results;
}

function validateLinks(routes) {
  const matchers = buildRouteMatchers(routes);
  const hrefs = collectInternalHrefs();
  const issues = [];

  for (const link of hrefs) {
    const exists = matchers.some((matcher) => matcher.regex.test(link.href));
    if (!exists) {
      issues.push(`Broken internal route reference: ${link.href} in ${path.relative(root, link.filePath)}`);
    }
  }

  return issues;
}

function parseClaimRegistry() {
  const content = read(claimFile);
  const idMatches = [...content.matchAll(/id:\s*'([^']+)'/g)].map((match) => match[1]);
  const statusMatches = [...content.matchAll(/status:\s*'([^']+)'/g)].map((match) => match[1]);
  const surfaceMatches = [...content.matchAll(/surfaces:\s*\[([^\]]+)\]/g)].map((match) => match[1]);

  return { idMatches, statusMatches, surfaceMatches };
}

function validateClaims() {
  const { idMatches, statusMatches, surfaceMatches } = parseClaimRegistry();
  const issues = [];

  const idSet = new Set();
  for (const id of idMatches) {
    if (idSet.has(id)) {
      issues.push(`Duplicate claim id: ${id}`);
    }
    idSet.add(id);
  }

  const validStatuses = new Set(['available_now', 'enterprise_on_request', 'roadmap']);
  for (const status of statusMatches) {
    if (!validStatuses.has(status)) {
      issues.push(`Invalid claim status: ${status}`);
    }
  }

  const surfaced = new Set();
  for (const surfaceGroup of surfaceMatches) {
    const surfaceIds = [...surfaceGroup.matchAll(/'([^']+)'/g)].map((match) => match[1]);
    surfaceIds.forEach((surface) => surfaced.add(surface));
  }

  const requiredSurfaces = [
    'home',
    'product',
    'pricing',
    'drivers',
    'circuits',
    'teams',
    'endurance',
    'waitlist',
    'security',
  ];

  for (const surface of requiredSurfaces) {
    if (!surfaced.has(surface)) {
      issues.push(`Missing claim coverage for surface: ${surface}`);
    }
  }

  return issues;
}

function main() {
  const routes = collectRoutes();
  const issues = [...validateLinks(routes), ...validateClaims()];

  if (issues.length > 0) {
    console.error('Content QA failed:');
    for (const issue of issues) {
      console.error(`- ${issue}`);
    }
    process.exit(1);
  }

  console.log(`Content QA passed. Checked ${routes.length} routes and claim registry consistency.`);
}

main();
