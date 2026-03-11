/**
 * Workaround for Next.js 14 Windows build bug:
 * The static export of pages/500.tsx fails on Windows because the
 * .next/export/500.html file is never created, causing the subsequent
 * rename to .next/server/pages/500.html to fail with ENOENT.
 *
 * This pre-build script ensures the target directory and file exist
 * so the rename succeeds (or is a no-op).
 */
import { mkdirSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';

const exportDir = join(process.cwd(), '.next', 'export');
const serverPagesDir = join(process.cwd(), '.next', 'server', 'pages');
const html = '<!DOCTYPE html><html><head><meta charset="utf-8"/></head><body><div id="__next"><div style="display:flex;justify-content:center;align-items:center;min-height:100vh;background:#0d0d0d;color:#e0e0e0;font-family:monospace"><div style="text-align:center"><h1 style="font-size:2rem;margin-bottom:0.5rem">500</h1><p style="opacity:0.6">Server error</p></div></div></div></body></html>';

for (const dir of [exportDir, serverPagesDir]) {
  mkdirSync(dir, { recursive: true });
}

for (const dir of [exportDir, serverPagesDir]) {
  const target = join(dir, '500.html');
  if (!existsSync(target)) {
    writeFileSync(target, html);
  }
}
