import sharp from 'sharp';
import { writeFile } from 'fs/promises';
import path from 'path';

/**
 * Export an approved candidate at multiple resolutions.
 *
 * @param {Object} options
 * @param {Buffer} options.png - original PNG buffer
 * @param {Object} options.coverage - coverage metrics
 * @param {Object} options.params - generation parameters
 * @param {number} options.seed
 * @param {string} options.outDir - output directory
 * @param {{ width: number, height: number }} [options.mobileSize] - mobile resolution
 * @returns {Promise<string[]>} list of written file paths
 */
export async function exportApproved({ png, coverage, params, seed, outDir, mobileSize }) {
  const written = [];

  // Desktop resolution (original)
  const desktopPath = path.join(outDir, 'approved.png');
  await writeFile(desktopPath, png);
  written.push(desktopPath);

  // Mobile resolution (resize if specified)
  if (mobileSize) {
    const mobilePng = await sharp(png)
      .resize(mobileSize.width, mobileSize.height, { fit: 'cover' })
      .png({ compressionLevel: 6 })
      .toBuffer();
    const mobilePath = path.join(outDir, 'approved_mobile.png');
    await writeFile(mobilePath, mobilePng);
    written.push(mobilePath);
  }

  // Dye field visualization — re-render not needed, just generate a
  // grayscale version from the original for debug/inspection
  const dyePng = await sharp(png)
    .grayscale()
    .png({ compressionLevel: 6 })
    .toBuffer();
  const dyePath = path.join(outDir, 'approved_dye.png');
  await writeFile(dyePath, dyePng);
  written.push(dyePath);

  // Metadata JSON
  const metadata = {
    seed,
    params,
    coverage: {
      black: Math.round(coverage.black * 10) / 10,
      white: Math.round(coverage.white * 10) / 10,
      gold: Math.round(coverage.gold * 10) / 10,
    },
    exportedAt: new Date().toISOString(),
  };
  const jsonPath = path.join(outDir, 'approved.json');
  await writeFile(jsonPath, JSON.stringify(metadata, null, 2));
  written.push(jsonPath);

  return written;
}
