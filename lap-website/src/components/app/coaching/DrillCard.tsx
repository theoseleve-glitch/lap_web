'use client';

import { useState } from 'react';
import type { Drill } from './types';

interface DrillCardProps {
  drill: Drill;
}

type Difficulty = 'beginner' | 'intermediate' | 'advanced';

const DIFFICULTY_COLORS: Record<Difficulty, string> = {
  beginner: 'text-acid-green border-acid-green',
  intermediate: 'text-marshal-yellow border-marshal-yellow',
  advanced: 'text-safety-red border-safety-red',
};

export default function DrillCard({ drill }: DrillCardProps) {
  const levels = drill.difficulty_progression;
  const availableLevels = levels
    ? (['beginner', 'intermediate', 'advanced'] as Difficulty[]).filter((d) => levels[d])
    : [];

  const [activeTab, setActiveTab] = useState<Difficulty>(availableLevels[0] ?? 'beginner');
  const activeLevel = levels?.[activeTab];

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-5">
      <h4 className="text-sm font-monument text-chalk mb-3">{drill.title}</h4>

      {availableLevels.length > 0 ? (
        <>
          {/* Tabs */}
          <div className="flex gap-2 mb-4">
            {availableLevels.map((level) => (
              <button
                type="button"
                key={level}
                onClick={() => setActiveTab(level)}
                className={`text-xs font-telemetry uppercase px-3 py-1 rounded-full border transition-colors ${
                  activeTab === level
                    ? DIFFICULTY_COLORS[level] + ' bg-white/5'
                    : 'text-steel border-steel/20 hover:border-steel/40'
                }`}
              >
                {level}
              </button>
            ))}
          </div>

          {/* Active level content */}
          {activeLevel && (
            <div className="space-y-2">
              <p className="text-xs text-chalk/80 font-body leading-relaxed">
                {activeLevel.description}
              </p>
              <div className="flex items-center gap-4 text-xs font-telemetry text-steel">
                <span>Laps: {activeLevel.lap_count}</span>
              </div>
              <div className="bg-asphalt/50 rounded-lg p-3">
                <span className="text-xs text-steel uppercase tracking-wider font-telemetry">Success Criteria</span>
                <p className="text-xs text-chalk/70 font-body mt-1">{activeLevel.success_criteria}</p>
              </div>
            </div>
          )}
        </>
      ) : (
        drill.description && (
          <p className="text-xs text-chalk/70 font-body leading-relaxed">{drill.description}</p>
        )
      )}
    </div>
  );
}
