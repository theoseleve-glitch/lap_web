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
        monument: ['var(--font-display)'],
        body: ['var(--font-body)'],
        telemetry: ['var(--font-mono)'],
      },
      fontSize: {
        'monument-xl': 'var(--text-monument-xl)',
        h1: 'var(--text-h1)',
        h2: 'var(--text-h2)',
        h3: 'var(--text-h3)',
        body: 'var(--text-body)',
        caption: 'var(--text-caption)',
        telemetry: 'var(--text-telemetry)',
        tiny: 'var(--text-tiny)',
      },
      lineHeight: {
        display: 'var(--lh-display)',
        heading: 'var(--lh-heading)',
        body: 'var(--lh-body)',
        label: 'var(--lh-label)',
      },
      letterSpacing: {
        display: 'var(--ls-display)',
        wide: 'var(--ls-wide)',
        medium: 'var(--ls-medium)',
        xwide: 'var(--ls-xwide)',
      },
      maxWidth: {
        prose: 'var(--max-prose)',
        wide: 'var(--max-wide)',
        tooltip: 'var(--max-tooltip)',
      },
      spacing: {
        'grid-margin': 'var(--grid-margin)',
        'grid-gutter': 'var(--grid-gutter)',
      },
      borderRadius: {
        0: '0px',
        1: '4px',
        2: '8px',
        DEFAULT: '8px',
        3: '12px',
        4: '16px',
        full: '9999px',
      },
      boxShadow: {
        'e0': 'var(--shadow-e0)',
        'e1': 'var(--shadow-e1)',
        'e2': 'var(--shadow-e2)',
        'e3': 'var(--shadow-e3)',
        'e4': 'var(--shadow-e4)',
      },
      borderWidth: {
        DEFAULT: 'var(--border-width-default)',
        2: 'var(--border-width-thick)',
      },
      borderColor: {
        DEFAULT: 'var(--border-color-default)',
        muted: 'var(--border-color-muted)',
        focus: 'var(--border-color-focus)',
        error: 'var(--border-color-error)',
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
