import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { spawn, spawnSync } from 'node:child_process';

const DEFAULT_BASE_URL = process.env.ASSET_CHECK_URL || 'http://localhost:3000';
const DEFAULT_PORT = Number(process.env.ASSET_CHECK_PORT || 3000);
const DEFAULT_CHUNK_LIMIT = Number(process.env.ASSET_CHECK_CHUNK_LIMIT || 6);
const DEFAULT_TIMEOUT_MS = Number(process.env.ASSET_CHECK_TIMEOUT_MS || 60000);
const POLL_INTERVAL_MS = 1500;

function parseArgs(argv) {
  const argSet = new Set(argv.slice(2));
  return {
    cleanStart: argSet.has('--clean-start'),
    reset: argSet.has('--reset'),
    baseUrl: process.env.ASSET_CHECK_URL || DEFAULT_BASE_URL,
    port: Number(process.env.ASSET_CHECK_PORT || DEFAULT_PORT),
    chunkLimit: Number(process.env.ASSET_CHECK_CHUNK_LIMIT || DEFAULT_CHUNK_LIMIT),
  };
}

function getNextBinPath() {
  return path.join(process.cwd(), 'node_modules', 'next', 'dist', 'bin', 'next');
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function cleanupNextBuildOutput() {
  const nextDir = path.join(process.cwd(), '.next');
  let lastError = null;

  for (let attempt = 1; attempt <= 6; attempt += 1) {
    try {
      await fs.promises.rm(nextDir, { recursive: true, force: true, maxRetries: 3, retryDelay: 120 });
      console.log(`[assets] removed ${nextDir}`);
      return;
    } catch (error) {
      lastError = error;
      await sleep(250 * attempt);
    }
  }

  throw lastError;
}

function killProcessOnPort(port) {
  if (process.platform === 'win32') {
    const psScript = `
      $conn = Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue
      if ($conn) {
        $conn | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
      }
    `;
    spawnSync('powershell', ['-NoProfile', '-Command', psScript], { stdio: 'ignore' });
    return;
  }

  spawnSync('sh', ['-c', `lsof -ti tcp:${port} | xargs -r kill -9`], { stdio: 'ignore' });
}

async function fetchText(url) {
  const response = await fetch(url, { redirect: 'follow' });
  if (!response.ok) {
    throw new Error(`GET ${url} -> ${response.status}`);
  }
  return response.text();
}

function extractMatches(content, pattern) {
  const results = [];
  let match = pattern.exec(content);
  while (match) {
    results.push(match[1]);
    match = pattern.exec(content);
  }
  return [...new Set(results)];
}

function toAbsoluteUrl(resourcePath, baseUrl) {
  if (/^https?:\/\//i.test(resourcePath)) {
    return resourcePath;
  }
  return new URL(resourcePath, baseUrl).toString();
}

async function checkResource(url) {
  try {
    const response = await fetch(url, { redirect: 'follow' });
    return { url, ok: response.status === 200, status: response.status };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown fetch error';
    return { url, ok: false, status: 0, error: message };
  }
}

async function runHealthCheck({ baseUrl, chunkLimit }) {
  const html = await fetchText(baseUrl);

  const cssPaths = extractMatches(
    html,
    /href="([^"]*\/_next\/static\/css\/[^"]+\.css[^"]*)"/g,
  );
  const chunkPaths = extractMatches(
    html,
    /src="([^"]*\/_next\/static\/chunks\/[^"]+\.js[^"]*)"/g,
  ).slice(0, chunkLimit);

  if (cssPaths.length === 0) {
    throw new Error(`No Next.js CSS assets found in ${baseUrl} HTML.`);
  }
  if (chunkPaths.length === 0) {
    throw new Error(`No Next.js chunk assets found in ${baseUrl} HTML.`);
  }

  const targets = [...cssPaths, ...chunkPaths].map((resource) => toAbsoluteUrl(resource, baseUrl));
  const results = [];
  for (const target of targets) {
    // Sequential to keep output deterministic and easy to read.
    // eslint-disable-next-line no-await-in-loop
    results.push(await checkResource(target));
  }

  let failed = 0;
  for (const result of results) {
    if (result.ok) {
      console.log(`[assets] OK   ${result.status} ${result.url}`);
    } else {
      failed += 1;
      const extra = result.error ? ` (${result.error})` : '';
      console.error(`[assets] FAIL ${result.status} ${result.url}${extra}`);
    }
  }

  if (failed > 0) {
    throw new Error(`Asset health check failed: ${failed} resource(s) returned non-200.`);
  }

  console.log(
    `[assets] healthy: checked ${cssPaths.length} css + ${chunkPaths.length} chunks from ${baseUrl}`,
  );
}

function startDevServerDetached(port) {
  const child = spawn(process.execPath, [getNextBinPath(), 'dev', '-p', String(port)], {
    detached: true,
    stdio: 'ignore',
  });
  child.unref();
  console.log(`[assets] started dev server in background on port ${port} (pid: ${child.pid})`);
}

function startDevServerForeground(port) {
  const child = spawn(process.execPath, [getNextBinPath(), 'dev', '-p', String(port)], {
    stdio: 'inherit',
  });

  child.on('exit', (code) => {
    process.exit(code ?? 0);
  });
}

async function waitForHealthyOrTimeout(options) {
  const startedAt = Date.now();
  let lastError = 'Not checked yet';

  while (Date.now() - startedAt <= DEFAULT_TIMEOUT_MS) {
    try {
      // eslint-disable-next-line no-await-in-loop
      await runHealthCheck(options);
      return;
    } catch (error) {
      lastError = error instanceof Error ? error.message : 'Unknown error';
      // eslint-disable-next-line no-await-in-loop
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }

  throw new Error(`Timed out waiting for healthy assets (${DEFAULT_TIMEOUT_MS}ms): ${lastError}`);
}

async function main() {
  const options = parseArgs(process.argv);

  if (options.cleanStart) {
    await cleanupNextBuildOutput();
    console.log(`[assets] starting dev server on ${options.baseUrl}`);
    startDevServerForeground(options.port);
    return;
  }

  if (options.reset) {
    console.log(`[assets] resetting dev runtime on port ${options.port}`);
    killProcessOnPort(options.port);
    await sleep(1200);
    await cleanupNextBuildOutput();
    startDevServerDetached(options.port);
    await waitForHealthyOrTimeout(options);
    return;
  }

  await runHealthCheck(options);
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`[assets] ${message}`);
  process.exit(1);
});
