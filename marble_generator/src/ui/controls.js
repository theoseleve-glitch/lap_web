/**
 * Controls — manages all UI control elements for marble generation.
 *
 * Reads DOM inputs for colors, physics, velocity, distribution, and
 * generation parameters. Provides getConfig() to collect all values,
 * and applyPreset() to load from the PRESETS object.
 */

import { PRESETS } from '../color/presets.js';
import { PRESET_NAMES } from '../engine/velocity-presets.js';

export class Controls {
  /**
   * @param {HTMLElement} containerEl - The .controls container element
   */
  constructor(containerEl) {
    this.container = containerEl;

    /** @type {Array<{hex: string, ratio: number, density: number, viscosity: number}>} */
    this.colors = [
      { hex: '#0a0a0c', ratio: 60, density: 1.0, viscosity: 0.001 },
      { hex: '#ebe6dc', ratio: 35, density: 1.0, viscosity: 0.001 },
      { hex: '#c3a54b', ratio: 5, density: 2.0, viscosity: 0.002 },
    ];

    /** @type {Function|null} */
    this.onChange = null;
  }

  /**
   * Collect the full configuration from all UI controls.
   *
   * @returns {{
   *   colors: Array<{hex: string, ratio: number, density: number, viscosity: number}>,
   *   distributionMode: string,
   *   physics: {viscosity: number, vorticity: number, diffusion: number, timestep: number, pressureIterations: number},
   *   velocity: {preset: string, magnitude: number, angle: number, turbulence: number},
   *   count: number,
   *   resolution: string,
   *   seed: string
   * }}
   */
  getConfig() {
    // Read color rows from DOM
    this._syncColorsFromDOM();

    return {
      colors: this.colors.map(c => ({ ...c })),
      distributionMode: this._getSelect('distributionMode') || 'veined',
      physics: {
        viscosity: this._getRange('physViscosity', 0.001),
        vorticity: this._getRange('physVorticity', 15),
        diffusion: this._getRange('physDiffusion', 0.0001),
        timestep: this._getRange('physTimestep', 0.5),
        pressureIterations: 40,
      },
      velocity: {
        preset: this._getSelect('velPreset') || 'curl-noise',
        magnitude: this._getRange('velMagnitude', 80),
        angle: this._getRange('velAngle', 0),
        turbulence: this._getRange('velTurbulence', 0),
      },
      count: parseInt(this._getInput('count', '5'), 10) || 5,
      resolution: this._getSelect('resolution') || '1920x1080',
      seed: this._getInput('seed', ''),
    };
  }

  /**
   * Apply a named marble preset from the PRESETS object.
   *
   * Updates internal colors array, rebuilds color rows in the DOM,
   * and sets the distribution mode dropdown.
   *
   * @param {string} name - Preset name (key in PRESETS)
   */
  applyPreset(name) {
    const preset = PRESETS[name];
    if (!preset) return;

    this.colors = preset.colors.map(c => ({
      hex: c.hex,
      ratio: c.ratio,
      density: c.density != null ? c.density : 1.0,
      viscosity: c.viscosity != null ? c.viscosity : 0.001,
    }));

    this._rebuildColorRows();
    this._setSelect('distributionMode', preset.mode || 'veined');

    if (this.onChange) this.onChange();
  }

  /**
   * Add a new color row (max 8 total).
   */
  addColor() {
    if (this.colors.length >= 8) return;
    this.colors.push({
      hex: '#808080',
      ratio: 10,
      density: 1.0,
      viscosity: 0.001,
    });
    this._rebuildColorRows();
    if (this.onChange) this.onChange();
  }

  /**
   * Remove a color row by index (min 2 colors).
   * @param {number} index
   */
  removeColor(index) {
    if (this.colors.length <= 2) return;
    if (index < 0 || index >= this.colors.length) return;
    this.colors.splice(index, 1);
    this._rebuildColorRows();
    if (this.onChange) this.onChange();
  }

  /**
   * Rebuild the color-rows container from the current colors array.
   * Called after applyPreset(), addColor(), or removeColor().
   */
  _rebuildColorRows() {
    const rowsContainer = document.getElementById('colorRows');
    if (!rowsContainer) return;

    // Clear existing rows
    while (rowsContainer.firstChild) {
      rowsContainer.removeChild(rowsContainer.firstChild);
    }

    this.colors.forEach((color, idx) => {
      const row = document.createElement('div');
      row.className = 'color-row';
      row.dataset.index = String(idx);

      // Color picker
      const colorInput = document.createElement('input');
      colorInput.type = 'color';
      colorInput.className = 'cr-color';
      colorInput.value = color.hex;

      // Ratio input
      const ratioLabel = document.createElement('label');
      ratioLabel.textContent = '%';
      const ratioInput = document.createElement('input');
      ratioInput.type = 'number';
      ratioInput.className = 'cr-ratio';
      ratioInput.min = '1';
      ratioInput.max = '100';
      ratioInput.value = String(color.ratio);

      // Density input
      const densLabel = document.createElement('label');
      densLabel.textContent = 'D';
      const densInput = document.createElement('input');
      densInput.type = 'number';
      densInput.className = 'cr-density';
      densInput.min = '0.5';
      densInput.max = '5.0';
      densInput.step = '0.1';
      densInput.value = String(color.density);

      // Viscosity input
      const viscLabel = document.createElement('label');
      viscLabel.textContent = 'V';
      const viscInput = document.createElement('input');
      viscInput.type = 'number';
      viscInput.className = 'cr-viscosity';
      viscInput.min = '0.0001';
      viscInput.max = '0.1';
      viscInput.step = '0.001';
      viscInput.value = String(color.viscosity);

      // Remove button
      const removeBtn = document.createElement('button');
      removeBtn.className = 'secondary cr-remove';
      removeBtn.textContent = '\u00D7';
      removeBtn.addEventListener('click', () => {
        this.removeColor(idx);
      });

      row.appendChild(colorInput);
      row.appendChild(ratioInput);
      row.appendChild(ratioLabel);
      row.appendChild(densInput);
      row.appendChild(densLabel);
      row.appendChild(viscInput);
      row.appendChild(viscLabel);
      row.appendChild(removeBtn);

      rowsContainer.appendChild(row);
    });
  }

  /**
   * Sync internal colors array from DOM color row inputs.
   * @private
   */
  _syncColorsFromDOM() {
    const rows = document.querySelectorAll('#colorRows .color-row');
    if (rows.length === 0) return;

    this.colors = [];
    rows.forEach((row) => {
      const colorEl = row.querySelector('.cr-color');
      const ratioEl = row.querySelector('.cr-ratio');
      const densEl = row.querySelector('.cr-density');
      const viscEl = row.querySelector('.cr-viscosity');

      this.colors.push({
        hex: colorEl ? colorEl.value : '#808080',
        ratio: ratioEl ? parseFloat(ratioEl.value) || 10 : 10,
        density: densEl ? parseFloat(densEl.value) || 1.0 : 1.0,
        viscosity: viscEl ? parseFloat(viscEl.value) || 0.001 : 0.001,
      });
    });
  }

  /**
   * Get value from a range input by ID.
   * @private
   * @param {string} id
   * @param {number} fallback
   * @returns {number}
   */
  _getRange(id, fallback) {
    const el = document.getElementById(id);
    return el ? parseFloat(el.value) : fallback;
  }

  /**
   * Get value from a select element by ID.
   * @private
   * @param {string} id
   * @returns {string}
   */
  _getSelect(id) {
    const el = document.getElementById(id);
    return el ? el.value : '';
  }

  /**
   * Get value from an input element by ID.
   * @private
   * @param {string} id
   * @param {string} fallback
   * @returns {string}
   */
  _getInput(id, fallback) {
    const el = document.getElementById(id);
    return el ? el.value : fallback;
  }

  /**
   * Set value on a select element by ID.
   * @private
   * @param {string} id
   * @param {string} value
   */
  _setSelect(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
  }
}
