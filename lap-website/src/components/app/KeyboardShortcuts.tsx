'use client';

import { useEffect, useState } from 'react';

const SHORTCUTS = [
  { keys: ['?'], description: 'Toggle this help overlay' },
  { keys: ['Esc'], description: 'Close overlay / deselect' },
  { keys: ['←', '→'], description: 'Navigate between laps' },
  { keys: ['↑', '↓'], description: 'Scroll through sessions' },
  { keys: ['1-9'], description: 'Select lap by number' },
  { keys: ['F'], description: 'Toggle fullscreen chart' },
  { keys: ['C'], description: 'Toggle compare mode' },
  { keys: ['R'], description: 'Reset zoom' },
] as const;

export function KeyboardShortcuts() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="bg-concrete border border-steel/20 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-chalk font-heading text-lg">Keyboard Shortcuts</h2>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-steel hover:text-chalk transition-colors text-sm"
          >
            Esc
          </button>
        </div>
        <div className="space-y-2">
          {SHORTCUTS.map((shortcut) => (
            <div key={shortcut.description} className="flex items-center justify-between py-1.5">
              <span className="text-steel text-sm">{shortcut.description}</span>
              <span className="flex gap-1">
                {shortcut.keys.map((key) => (
                  <kbd
                    key={key}
                    className="px-2 py-0.5 bg-asphalt border border-steel/20 rounded text-xs font-telemetry text-chalk min-w-[24px] text-center"
                  >
                    {key}
                  </kbd>
                ))}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-4 text-steel/60 text-xs text-center">
          Press <kbd className="px-1 py-0.5 bg-asphalt border border-steel/20 rounded text-[10px]">?</kbd> to toggle
        </p>
      </div>
    </div>
  );
}
