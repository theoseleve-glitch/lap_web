/**
 * Marble preset definitions.
 *
 * Each preset specifies an array of colors with ratios
 * and a distribution mode name that maps to a function
 * in distribution.js.
 */

export const PRESETS = {
  'Nero Marquina': {
    colors: [
      { hex: '#0a0a0c', ratio: 60 },
      { hex: '#ebe6dc', ratio: 35 },
      { hex: '#c3a54b', ratio: 5 },
    ],
    mode: 'veined',
  },

  'Calacatta Gold': {
    colors: [
      { hex: '#f5f0e8', ratio: 70 },
      { hex: '#d4c9a8', ratio: 20 },
      { hex: '#b89b4f', ratio: 10 },
    ],
    mode: 'veined',
  },

  'Verde Guatemala': {
    colors: [
      { hex: '#1a3a2a', ratio: 50 },
      { hex: '#3d7a5a', ratio: 35 },
      { hex: '#e8e0d0', ratio: 15 },
    ],
    mode: 'veined',
  },

  'Rosso Levanto': {
    colors: [
      { hex: '#6b1a1a', ratio: 45 },
      { hex: '#a83232', ratio: 40 },
      { hex: '#f0e8dc', ratio: 15 },
    ],
    mode: 'veined',
  },

  'Blue Sodalite': {
    colors: [
      { hex: '#0d1b3a', ratio: 40 },
      { hex: '#1a3a6b', ratio: 30 },
      { hex: '#c3a54b', ratio: 10 },
      { hex: '#e8e0d0', ratio: 20 },
    ],
    mode: 'veined',
  },

  'Arabescato': {
    colors: [
      { hex: '#f2ede5', ratio: 65 },
      { hex: '#b0a898', ratio: 25 },
      { hex: '#555045', ratio: 10 },
    ],
    mode: 'clustered',
  },

  'Portoro': {
    colors: [
      { hex: '#0a0a0a', ratio: 75 },
      { hex: '#c3a54b', ratio: 18 },
      { hex: '#e8d888', ratio: 7 },
    ],
    mode: 'veined',
  },

  'Rainbow Onyx': {
    colors: [
      { hex: '#e8d0b0', ratio: 30 },
      { hex: '#c87850', ratio: 20 },
      { hex: '#6b4030', ratio: 20 },
      { hex: '#3a5040', ratio: 15 },
      { hex: '#d4a840', ratio: 15 },
    ],
    mode: 'swirl',
  },
};
