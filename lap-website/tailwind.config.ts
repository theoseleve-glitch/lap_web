import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        asphalt: '#000000',
        concrete: '#141414',
        chalk: '#F0EDE5',
        steel: '#8A8F98',
        'acid-green': '#4ADE80',
        'safety-red': '#FF2A2A',
        'marshal-yellow': '#FACC15',
        'pit-orange': '#C9A84C',
        'racing-purple': '#A78BFA',
        gold: '#C9A84C',
      },
      fontFamily: {
        monument: ['"Space Grotesk"', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
        telemetry: ['"Space Mono"', 'monospace'],
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
        hud: 35,
        drs: 36,
        'finish-line': 37,
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
