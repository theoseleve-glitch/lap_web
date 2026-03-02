'use client';

import type { SectionDef } from './types';

interface AnalyzerSectionTabsProps {
  sections: SectionDef[];
  activeSection: string;
  onSectionChange: (id: string) => void;
}

const TYPE_STYLES: Record<string, string> = {
  full: 'border-acid-green/40 text-acid-green',
  straight: 'border-steel/30 text-steel',
  corner: 'border-pit-orange/40 text-pit-orange',
};

export function AnalyzerSectionTabs({ sections, activeSection, onSectionChange }: AnalyzerSectionTabsProps) {
  return (
    <div className="flex items-center gap-1 px-4 py-2 bg-concrete/50 border-b border-steel/10 overflow-x-auto scrollbar-none">
      {sections.map((s, i) => {
        const isActive = s.id === activeSection;
        const base = TYPE_STYLES[s.type] ?? TYPE_STYLES.straight;
        return (
          <button
            key={s.id}
            onClick={() => onSectionChange(s.id)}
            className={`shrink-0 px-3 py-1.5 text-xs font-telemetry rounded border transition-all ${
              isActive
                ? `${base} bg-white/5 border-current`
                : 'border-transparent text-steel/60 hover:text-chalk hover:bg-white/5'
            }`}
            title={`${s.label} (${Math.round(s.startDist)}m – ${Math.round(s.endDist)}m)`}
          >
            {i < 10 && (
              <kbd className="inline-block mr-1 text-[9px] opacity-40">{i + 1}</kbd>
            )}
            {s.label}
          </button>
        );
      })}
    </div>
  );
}
