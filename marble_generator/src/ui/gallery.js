/**
 * Gallery — manages the card grid display for generated marble results.
 *
 * Each card contains a canvas preview and info bar showing the seed
 * and per-color coverage percentages. Cards are clickable to open
 * the interactive Studio view.
 */

export class Gallery {
  /**
   * @param {HTMLElement} galleryEl - The .gallery container element
   * @param {HTMLElement} progressEl - The .progress-area container element
   */
  constructor(galleryEl, progressEl) {
    this.galleryEl = galleryEl;
    this.progressEl = progressEl;

    /** @type {Array<object>} */
    this.results = [];

    /** @type {boolean} */
    this.generating = false;

    /** @type {Function|null} */
    this.onCardClick = null;
  }

  /**
   * Add a card to the gallery for a generated result.
   *
   * Creates DOM elements using safe methods (createElement, textContent,
   * appendChild). The canvas displays the pixel data from the result.
   *
   * @param {object} result - Generated marble result with data, width, height, seed, cov
   */
  addCard(result) {
    // Remove empty state if present
    const emptyState = document.getElementById('emptyState');
    if (emptyState) emptyState.remove();

    this.results.push(result);

    const card = document.createElement('div');
    card.className = 'card';

    // Canvas with rendered marble
    const cvs = document.createElement('canvas');
    cvs.width = result.width;
    cvs.height = result.height;
    const ctx = cvs.getContext('2d');
    if (result.data instanceof Uint8ClampedArray) {
      ctx.putImageData(
        new ImageData(new Uint8ClampedArray(result.data), result.width, result.height),
        0, 0
      );
    } else if (result.data instanceof ImageData) {
      ctx.putImageData(result.data, 0, 0);
    }

    // Info bar
    const info = document.createElement('div');
    info.className = 'card-info';

    const seedSpan = document.createElement('span');
    seedSpan.className = 'seed';
    seedSpan.textContent = 'Seed: ' + result.seed;

    const covSpan = document.createElement('span');
    covSpan.className = 'coverage';

    if (result.cov) {
      const keys = Object.keys(result.cov);
      keys.forEach((key, i) => {
        const s = document.createElement('span');
        const classes = ['cov-a', 'cov-b', 'cov-c'];
        s.className = classes[i % classes.length];
        s.textContent = key + ':' + result.cov[key].toFixed(1) + '%';
        covSpan.appendChild(s);
      });
    }

    info.appendChild(seedSpan);
    info.appendChild(covSpan);
    card.appendChild(cvs);
    card.appendChild(info);

    card.addEventListener('click', () => {
      if (this.onCardClick) {
        this.onCardClick(result);
      }
    });

    this.galleryEl.appendChild(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /**
   * Clear all cards from the gallery and reset results.
   */
  clear() {
    while (this.galleryEl.firstChild) {
      this.galleryEl.removeChild(this.galleryEl.firstChild);
    }

    const emptyDiv = document.createElement('div');
    emptyDiv.className = 'empty-state';
    emptyDiv.id = 'emptyState';

    const p1 = document.createElement('p');
    p1.textContent = 'Click Generate to create marble backgrounds with fluid simulation.';
    const p2 = document.createElement('p');
    p2.textContent = 'Click any result to open Studio \u2014 drag to push ink with Navier-Stokes physics.';

    emptyDiv.appendChild(p1);
    emptyDiv.appendChild(p2);
    this.galleryEl.appendChild(emptyDiv);

    this.results = [];
  }

  /**
   * Show generation progress.
   *
   * @param {number} current - Current item number
   * @param {number} total - Total items to generate
   * @param {number} elapsed - Elapsed time in seconds
   */
  showProgress(current, total, elapsed) {
    this.progressEl.classList.add('active');
    const fill = this.progressEl.querySelector('.progress-bar-fill');
    const text = this.progressEl.querySelector('.progress-text');
    if (fill) fill.style.width = (current / total * 100) + '%';
    if (text) text.textContent = current + ' / ' + total + ' (' + elapsed.toFixed(1) + 's)';
  }

  /**
   * Hide the progress bar.
   */
  hideProgress() {
    this.progressEl.classList.remove('active');
  }
}
