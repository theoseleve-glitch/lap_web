/**
 * Workaround for Next.js 14 + Node 25 — the webpack plugin that generates
 * middleware-manifest.json fails silently. This script creates it post-build.
 */
import { existsSync, writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const serverDir = join(__dirname, '..', '.next', 'server');
const manifestPath = join(serverDir, 'middleware-manifest.json');

if (!existsSync(manifestPath)) {
  mkdirSync(serverDir, { recursive: true });
  const manifest = {
    sortedMiddleware: ['/'],
    middleware: {
      '/': {
        files: ['server/src/middleware.js'],
        name: 'middleware',
        page: '/',
        matchers: [
          {
            regexp: '^((?!_next/static|_next/image|favicon\\.ico|robots\\.txt|sitemap\\.xml|manifest\\.json|.*\\.(?:png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot|css|js|map|webp|avif)).*)',
            originalSource: '/((?!_next/static|_next/image|favicon\\.ico|robots\\.txt|sitemap\\.xml|manifest\\.json|.*\\.(?:png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot|css|js|map|webp|avif)).*)',
          },
        ],
        wasm: [],
        assets: [],
      },
    },
    functions: {},
    version: 2,
  };
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  console.log('Created middleware-manifest.json (Node 25 workaround)');
} else {
  console.log('middleware-manifest.json already exists');
}
