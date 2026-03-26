/**
 * ChartThemePicker.tsx — Dropdown to select chart color theme.
 *
 * Reads/writes via window.Theme.setChartTheme() (vanilla JS).
 * Persists choice to localStorage via the theme.js module.
 */
'use client';

import { useState, useEffect } from 'react';

interface ThemeAPI {
  setChartTheme: (name: string) => void;
  getChartThemeName: () => string;
  getChartThemeNames: () => string[];
  CHART_THEMES: Record<string, string[]>;
}

const LABELS: Record<string, string> = {
  default: 'Default',
  highContrast: 'High Contrast',
  colorblind: 'Colorblind-safe',
};

export function ChartThemePicker() {
  const [current, setCurrent] = useState('default');
  const [themes, setThemes] = useState<string[]>([]);
  const [palettes, setPalettes] = useState<Record<string, string[]>>({});

  useEffect(() => {
    const T = (window as unknown as { Theme?: ThemeAPI }).Theme;
    if (!T?.getChartThemeNames) return;
    setThemes(T.getChartThemeNames());
    setCurrent(T.getChartThemeName());
    setPalettes(T.CHART_THEMES);
  }, []);

  const handleChange = (name: string) => {
    const T = (window as unknown as { Theme?: ThemeAPI }).Theme;
    if (!T?.setChartTheme) return;
    T.setChartTheme(name);
    setCurrent(name);
  };

  if (!themes.length) return null;

  return (
    <div className="flex items-center gap-2 text-xs font-body">
      <span className="text-steel">Theme:</span>
      <div className="flex gap-1">
        {themes.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => handleChange(name)}
            title={LABELS[name] || name}
            className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors ${
              current === name
                ? 'border-acid-green text-acid-green'
                : 'border-steel/20 text-steel hover:text-chalk hover:border-steel/40'
            }`}
          >
            {/* Color preview dots */}
            <span className="flex gap-px">
              {(palettes[name] || []).slice(0, 4).map((c, i) => (
                <span
                  key={i}
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ backgroundColor: c }}
                />
              ))}
            </span>
            <span className="hidden sm:inline">{LABELS[name] || name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
