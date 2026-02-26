import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        asphalt: '#0B0C0F',
        concrete: '#161A20',
        chalk: '#F3F0E8',
        steel: '#8A8F98',
        'acid-green': '#B6FF2E',
        'safety-red': '#FF2A2A',
        'marshal-yellow': '#FFD400',
        'pit-orange': '#FF6A00',
      },
      fontFamily: {
        monument: ['Teko', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        telemetry: ['IBM Plex Mono', 'monospace'],
      },
      spacing: {
        'grid-margin': 'var(--grid-margin)',
        'grid-gutter': 'var(--grid-gutter)',
      },
      zIndex: {
        base: 0,
        panels: 10,
        stamps: 20,
        delta: 30,
        sector: 40,
        timecode: 50,
        nav: 60,
        overlay: 100,
        cursor: 999,
      } as unknown as Record<string, string>,
    },
  },
  plugins: [],
};

export default config;
