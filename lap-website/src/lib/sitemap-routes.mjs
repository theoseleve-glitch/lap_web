import fs from 'node:fs';
import path from 'node:path';

function walk(dir, predicate) {
  if (!fs.existsSync(dir)) {
    return [];
  }

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

function normalizeRoute(route) {
  if (!route) return '/';
  const cleaned = route.endsWith('/') && route !== '/' ? route.slice(0, -1) : route;
  return cleaned || '/';
}

function stripRouteGroups(route) {
  return route.replace(/\/\([^/]+\)/g, '');
}

function toRoute(appDir, pagePath) {
  const relative = path.relative(appDir, pagePath).replace(/\\/g, '/');
  const withoutPage = relative.replace(/\/page\.(tsx|ts|jsx|js)$/, '').replace(/^page\.(tsx|ts|jsx|js)$/, '');
  const route = stripRouteGroups(`/${withoutPage}`);
  return normalizeRoute(route);
}

export function collectAppPageRoutes(rootDir = process.cwd()) {
  const appDir = path.join(rootDir, 'src', 'app');
  const pages = walk(appDir, (filePath) => /\/page\.(tsx|ts|jsx|js)$/.test(filePath));
  return pages.map((pagePath) => toRoute(appDir, pagePath));
}

export function collectMarketingSitemapRoutes(rootDir = process.cwd()) {
  const appDir = path.join(rootDir, 'src', 'app');
  const marketingDir = path.join(appDir, '(marketing)');
  const pages = walk(marketingDir, (filePath) => /\/page\.(tsx|ts|jsx|js)$/.test(filePath));

  const routes = pages
    .map((pagePath) => toRoute(appDir, pagePath))
    .filter((route) => !route.includes('['));

  return [...new Set(routes)].sort((a, b) => a.localeCompare(b));
}
