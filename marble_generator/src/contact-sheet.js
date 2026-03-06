import sharp from 'sharp';
import { readFile, readdir, writeFile } from 'fs/promises';
import path from 'path';

const COLS = 5;
const THUMB_W = 320;
const THUMB_H = 180;
const PADDING = 8;
const LABEL_H = 24;

/**
 * Create a contact sheet from candidate PNGs in the output directory.
 *
 * @param {string} outDir - directory containing candidate_NNN.png and index.json
 * @returns {Promise<string>} path to generated contact sheet
 */
export async function createContactSheet(outDir) {
  // Load index to get metadata
  const indexPath = path.join(outDir, 'index.json');
  let index;
  try {
    index = JSON.parse(await readFile(indexPath, 'utf8'));
  } catch {
    throw new Error(`No index.json found in ${outDir}. Run generate first.`);
  }

  if (index.length === 0) throw new Error('No candidates in index.json');

  const rows = Math.ceil(index.length / COLS);
  const cellW = THUMB_W + PADDING;
  const cellH = THUMB_H + LABEL_H + PADDING;
  const sheetW = COLS * cellW + PADDING;
  const sheetH = rows * cellH + PADDING;

  // Create dark background
  const composites = [];

  for (let i = 0; i < index.length; i++) {
    const entry = index[i];
    const col = i % COLS;
    const row = Math.floor(i / COLS);
    const x = PADDING + col * cellW;
    const y = PADDING + row * cellH;

    // Resize candidate to thumbnail
    const imgPath = path.join(outDir, entry.filename);
    const thumb = await sharp(imgPath)
      .resize(THUMB_W, THUMB_H, { fit: 'cover' })
      .toBuffer();

    composites.push({ input: thumb, left: x, top: y });

    // Create label with ID and coverage
    const cov = entry.coverage;
    const labelText = `#${entry.id} B:${cov.black.toFixed(0)}% W:${cov.white.toFixed(0)}% G:${cov.gold.toFixed(0)}%`;
    const labelSvg = Buffer.from(`
      <svg width="${THUMB_W}" height="${LABEL_H}">
        <rect width="${THUMB_W}" height="${LABEL_H}" fill="#1a1a1a"/>
        <text x="4" y="17" font-family="monospace" font-size="12" fill="#cccccc">${labelText}</text>
      </svg>
    `);
    const labelPng = await sharp(labelSvg).png().toBuffer();
    composites.push({ input: labelPng, left: x, top: y + THUMB_H });
  }

  const sheet = await sharp({
    create: { width: sheetW, height: sheetH, channels: 4, background: { r: 20, g: 20, b: 22, alpha: 1 } },
  })
    .composite(composites)
    .png({ compressionLevel: 6 })
    .toBuffer();

  const sheetPath = path.join(outDir, 'contact_sheet.png');
  await writeFile(sheetPath, sheet);
  return sheetPath;
}
