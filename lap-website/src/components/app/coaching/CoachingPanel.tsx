'use client';

import type { CoachingV3Data } from './types';
import SessionTheme from './SessionTheme';
import FocusAreaCard from './FocusAreaCard';
import DrillCard from './DrillCard';
import NextSessionGoals from './NextSessionGoals';
import StrengthsList from './StrengthsList';
import DeferredAreas from './DeferredAreas';
import CornerCoachingCard from './CornerCoachingCard';

interface CoachingPanelProps {
  data: CoachingV3Data;
  grade?: string | null;
  className?: string;
}

export default function CoachingPanel({ data, grade, className = '' }: CoachingPanelProps) {
  const hasCornerCoaching = data.corner_coaching && data.corner_coaching.length > 0;
  const topFocusAreas = data.focus_areas?.slice(0, 2) ?? [];

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Session Theme */}
      <SessionTheme
        grade={grade}
        session_theme={data.session_theme}
        narrative={data.narrative}
        confidence={data.confidence}
      />

      {/* Focus Areas (top 2) */}
      {topFocusAreas.length > 0 && (
        <section>
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-3">Focus Areas</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {topFocusAreas.map((area, i) => (
              <FocusAreaCard key={i} area={area} />
            ))}
          </div>
        </section>
      )}

      {/* Corner Coaching (V3) */}
      {hasCornerCoaching && (
        <section>
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-3">Corner Coaching</h3>
          <div className="space-y-3">
            {data.corner_coaching!.map((corner) => (
              <CornerCoachingCard key={corner.corner_id} corner={corner} />
            ))}
          </div>
        </section>
      )}

      {/* Drills */}
      {data.drills && data.drills.length > 0 && (
        <section>
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-3">Development Drills</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.drills.map((drill, i) => (
              <DrillCard key={i} drill={drill} />
            ))}
          </div>
        </section>
      )}

      {/* Next Session Goals */}
      <NextSessionGoals goals={data.next_session_goals} />

      {/* Strengths */}
      <StrengthsList strengths={data.strengths} />

      {/* Deferred Areas */}
      <DeferredAreas areas={data.deferred_focus_areas} />
    </div>
  );
}
