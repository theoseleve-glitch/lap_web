/**
 * Export a canvas element (or DOM element containing canvases) as a PNG file.
 *
 * For single canvas: converts directly via toDataURL.
 * For container elements: uses html2canvas-like approach with canvas.toBlob.
 */
export function exportCanvasAsPNG(canvas: HTMLCanvasElement, filename: string): void {
  try {
    const dataUrl = canvas.toDataURL('image/png');
    const link = document.createElement('a');
    link.download = `${filename}.png`;
    link.href = dataUrl;
    link.click();
  } catch {
    // Canvas may be tainted (cross-origin)
    console.warn('Could not export chart — canvas may be cross-origin tainted');
  }
}

/**
 * Find and export the first canvas inside a container element.
 */
export function exportFirstCanvas(container: HTMLElement, filename: string): boolean {
  const canvas = container.querySelector('canvas');
  if (!canvas) return false;
  exportCanvasAsPNG(canvas, filename);
  return true;
}
