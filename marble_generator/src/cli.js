#!/usr/bin/env node
import { Command } from 'commander';
import { mkdir, writeFile, readFile } from 'fs/promises';
import path from 'path';
import { generateMarble, generateMarbleV2, DEFAULTS } from './generator.js';
import { createContactSheet } from './contact-sheet.js';
import { exportApproved } from './export.js';
import { PRESETS } from './color/presets.js';
import { createPalette } from './color/palette.js';
import { PRESET_NAMES } from './engine/velocity-presets.js';
import { MODES } from './color/distribution.js';

const program = new Command();

program
  .name('marble')
  .description('Premium fluid-marbling background image generator')
  .version('1.0.0');

/**
 * Resolve a palette from CLI options.
 * Returns null if neither --preset nor --colors is given (use legacy path).
 *
 * @param {Object} opts - parsed CLI options
 * @returns {{ palette: Object, distribution: string } | null}
 */
function resolvePalette(opts) {
  if (opts.preset) {
    const preset = PRESETS[opts.preset];
    if (!preset) {
      const names = Object.keys(PRESETS).join(', ');
      console.error(`Error: Unknown preset "${opts.preset}". Available: ${names}`);
      process.exit(1);
    }
    const palette = createPalette(preset.colors);
    // CLI --distribution overrides the preset default
    const distribution = opts.distribution || preset.mode || 'veined';
    return { palette, distribution };
  }

  if (opts.colors) {
    let entries;
    try {
      entries = JSON.parse(opts.colors);
    } catch (e) {
      console.error(`Error: Invalid --colors JSON: ${e.message}`);
      process.exit(1);
    }
    if (!Array.isArray(entries) || entries.length < 2) {
      console.error('Error: --colors must be a JSON array with at least 2 color entries');
      process.exit(1);
    }
    for (const entry of entries) {
      if (!entry.hex || entry.ratio == null) {
        console.error('Error: Each color entry must have "hex" and "ratio" fields');
        process.exit(1);
      }
    }
    const palette = createPalette(entries);
    const distribution = opts.distribution || 'veined';
    return { palette, distribution };
  }

  return null;
}

/**
 * Format coverage output for V2 (N-color) results.
 *
 * @param {Object} coverage - from computeCoverageV2
 * @returns {string} formatted coverage string
 */
function formatCoverageV2(coverage) {
  if (!coverage.colorDetails) return '';
  return coverage.colorDetails
    .map((d) => `${d.hex}:${d.percentage.toFixed(1)}%`)
    .join(' ');
}

/**
 * Build coverage object for index.json from V2 results.
 *
 * @param {Object} coverage - from computeCoverageV2
 * @returns {Object} simplified coverage for serialization
 */
function buildIndexCoverageV2(coverage) {
  if (!coverage.colorDetails) return {};
  const result = {};
  for (const d of coverage.colorDetails) {
    result[d.hex] = Math.round(d.percentage * 10) / 10;
  }
  return result;
}

// ── generate ─────────────────────────────────────────────
program
  .command('generate')
  .description('Generate marble background candidates')
  .option('-n, --count <number>', 'Number of candidates to generate', '5')
  .option('-o, --out <dir>', 'Output directory', 'outputs')
  .option('-r, --resolution <WxH>', 'Resolution (e.g. 1920x1080)', '1920x1080')
  .option('-s, --seed <number>', 'Fixed seed (random if omitted)')
  .option('--preset <name>', `Marble preset (${Object.keys(PRESETS).join(', ')})`)
  .option('--colors <json>', 'Custom colors as JSON array, e.g. \'[{"hex":"#1a3a2a","ratio":50},{"hex":"#3d7a5a","ratio":35}]\'')
  .option('--distribution <mode>', `Distribution mode (${Object.keys(MODES).join(', ')})`, 'veined')
  .option('--velocity <preset>', `Velocity preset (${PRESET_NAMES.join(', ')})`)
  .option('--magnitude <n>', 'Velocity magnitude 0-200', '80')
  .option('--viscosity <n>', 'Fluid viscosity 0.0001-0.1', '0.001')
  .option('--vorticity <n>', 'Vorticity confinement 0-50', '15')
  .action(async (opts) => {
    const count = parseInt(opts.count, 10);
    const [width, height] = opts.resolution.split('x').map(Number);
    const outDir = path.resolve(opts.out);
    await mkdir(outDir, { recursive: true });

    // Determine if we use V2 (N-color) or legacy pipeline
    const paletteInfo = resolvePalette(opts);
    const useV2 = paletteInfo !== null;

    if (useV2) {
      const presetLabel = opts.preset || 'custom';
      console.log(`Generating ${count} marble candidates at ${width}x${height} [${presetLabel}, ${paletteInfo.distribution}]...`);
    } else {
      console.log(`Generating ${count} marble candidates at ${width}x${height}...`);
    }

    // Build velocity config if --velocity is specified
    let velocityConfig = null;
    if (opts.velocity) {
      if (!PRESET_NAMES.includes(opts.velocity)) {
        console.error(`Error: Unknown velocity preset "${opts.velocity}". Available: ${PRESET_NAMES.join(', ')}`);
        process.exit(1);
      }
      velocityConfig = {
        preset: opts.velocity,
        magnitude: parseFloat(opts.magnitude),
        angle: 0,
        turbulence: parseFloat(opts.vorticity),
      };
    }

    const index = [];

    for (let i = 0; i < count; i++) {
      const seed = opts.seed ? parseInt(opts.seed, 10) + i : Math.floor(Math.random() * 1_000_000);
      const id = i + 1;
      const filename = `candidate_${String(id).padStart(3, '0')}.png`;

      process.stdout.write(`  [${id}/${count}] seed=${seed} ... `);
      const start = Date.now();

      let result;
      if (useV2) {
        result = await generateMarbleV2({
          width,
          height,
          seed,
          palette: paletteInfo.palette,
          distribution: paletteInfo.distribution,
          velocity: velocityConfig,
        });
      } else {
        result = await generateMarble({ width, height, seed });
      }

      const elapsed = ((Date.now() - start) / 1000).toFixed(1);
      const cov = result.coverage;

      if (useV2) {
        console.log(`${elapsed}s  ${formatCoverageV2(cov)}`);
      } else {
        console.log(
          `${elapsed}s  B:${cov.black.toFixed(1)}% W:${cov.white.toFixed(1)}% G:${cov.gold.toFixed(1)}%  (${result.tuneIterations} tune iters)`
        );
      }

      await writeFile(path.join(outDir, filename), result.png);

      const indexEntry = {
        id,
        filename,
        seed: result.seed,
        parameters: result.params,
      };

      if (useV2) {
        indexEntry.preset = opts.preset || null;
        indexEntry.distribution = paletteInfo.distribution;
        indexEntry.velocity = velocityConfig;
        indexEntry.coverage = buildIndexCoverageV2(cov);
      } else {
        indexEntry.coverage = {
          black: Math.round(cov.black * 10) / 10,
          white: Math.round(cov.white * 10) / 10,
          gold: Math.round(cov.gold * 10) / 10,
        };
      }

      index.push(indexEntry);
    }

    await writeFile(path.join(outDir, 'index.json'), JSON.stringify(index, null, 2));
    console.log(`\nDone! ${count} candidates saved to ${outDir}/`);
    console.log(`Index written to ${outDir}/index.json`);
  });

// ── contact-sheet ────────────────────────────────────────
program
  .command('contact-sheet')
  .description('Create a thumbnail contact sheet from generated candidates')
  .option('-o, --out <dir>', 'Directory with candidates', 'outputs')
  .action(async (opts) => {
    const outDir = path.resolve(opts.out);
    console.log(`Creating contact sheet from ${outDir}/...`);
    const sheetPath = await createContactSheet(outDir);
    console.log(`Contact sheet saved to ${sheetPath}`);
  });

// ── export ───────────────────────────────────────────────
program
  .command('export')
  .description('Export an approved candidate at multiple resolutions')
  .requiredOption('-i, --id <number>', 'Candidate ID to export')
  .option('-o, --out <dir>', 'Output directory', 'outputs')
  .option('-r, --resolution <WxH>', 'Desktop resolution', '1920x1080')
  .option('-m, --mobile <WxH>', 'Mobile resolution (e.g. 1170x2532)')
  .action(async (opts) => {
    const outDir = path.resolve(opts.out);
    const indexPath = path.join(outDir, 'index.json');

    let index;
    try {
      index = JSON.parse(await readFile(indexPath, 'utf8'));
    } catch {
      console.error(`Error: No index.json found in ${outDir}. Run generate first.`);
      process.exit(1);
    }

    const id = parseInt(opts.id, 10);
    const entry = index.find((e) => e.id === id);
    if (!entry) {
      console.error(`Error: Candidate #${id} not found in index.json`);
      process.exit(1);
    }

    console.log(`Exporting candidate #${id} (seed=${entry.seed})...`);

    // Re-generate at requested resolution for best quality
    const [width, height] = opts.resolution.split('x').map(Number);
    const result = await generateMarble({
      width,
      height,
      seed: entry.seed,
      params: entry.parameters,
    });

    let mobileSize;
    if (opts.mobile) {
      const [mw, mh] = opts.mobile.split('x').map(Number);
      mobileSize = { width: mw, height: mh };
    }

    const written = await exportApproved({
      png: result.png,
      coverage: result.coverage,
      params: result.params,
      seed: result.seed,
      outDir,
      mobileSize,
    });

    console.log('Exported files:');
    written.forEach((f) => console.log(`  ${f}`));
  });

program.parse();
