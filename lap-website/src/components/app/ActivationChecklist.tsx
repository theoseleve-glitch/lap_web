'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface ChecklistItem {
  id: string;
  label: string;
  href: string;
  description: string;
}

const CHECKLIST: ChecklistItem[] = [
  { id: 'upload', label: 'Upload your first session', href: '/app/analyze', description: 'Import a CSV from RaceChrono, RaceBox, AiM, or MoTeC.' },
  { id: 'review', label: 'Review your coaching report', href: '/app/sessions', description: 'Check your 4-pillar score and corner-by-corner coaching hints.' },
  { id: 'profile', label: 'Set your display name', href: '/app/account', description: 'Personalize your profile for leaderboards and reports.' },
  { id: 'second', label: 'Upload a second session', href: '/app/analyze', description: 'Track your progress across multiple sessions.' },
  { id: 'compare', label: 'Compare two sessions', href: '/app/compare', description: 'See exactly where you gained or lost time between runs.' },
];

const STORAGE_KEY = 'lap_activation_checklist';

export function ActivationChecklist() {
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed.dismissed) { setDismissed(true); return; }
        if (parsed.completed) setCompleted(new Set(parsed.completed));
      }
    } catch { /* ignore */ }
  }, []);

  function toggle(id: string) {
    setCompleted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ completed: [...next] }));
      return next;
    });
  }

  function dismiss() {
    setDismissed(true);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ dismissed: true }));
  }

  if (dismissed) return null;

  const progress = completed.size / CHECKLIST.length;

  return (
    <div className="bg-concrete rounded-xl border border-acid-green/20 p-5 mb-6">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-monument text-sm text-chalk">Getting Started</h3>
        <button
          onClick={dismiss}
          className="text-steel/40 hover:text-steel text-xs font-telemetry transition-colors"
        >
          Dismiss
        </button>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1.5 bg-steel/10 rounded-full mb-4 overflow-hidden">
        <div
          className="h-full bg-acid-green rounded-full transition-all duration-500"
          style={{ width: `${progress * 100}%` }}
        />
      </div>
      <p className="text-steel font-telemetry text-[10px] tracking-wider uppercase mb-3">
        {completed.size} of {CHECKLIST.length} complete
      </p>

      <ul className="space-y-2">
        {CHECKLIST.map((item) => {
          const done = completed.has(item.id);
          return (
            <li key={item.id} className="flex items-start gap-3">
              <button
                onClick={() => toggle(item.id)}
                className={`mt-0.5 w-5 h-5 rounded border flex-shrink-0 flex items-center justify-center transition-colors ${
                  done ? 'bg-acid-green border-acid-green text-carbon' : 'border-steel/30 hover:border-steel/60'
                }`}
                aria-label={`Mark "${item.label}" as ${done ? 'incomplete' : 'complete'}`}
              >
                {done && <span className="text-xs font-bold">&#10003;</span>}
              </button>
              <div className="flex-1 min-w-0">
                <Link
                  href={item.href}
                  className={`block text-sm font-body transition-colors ${
                    done ? 'text-steel/50 line-through' : 'text-chalk hover:text-acid-green'
                  }`}
                >
                  {item.label}
                </Link>
                <p className="text-[11px] text-steel/50 font-body">{item.description}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
