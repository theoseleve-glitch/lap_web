'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api-client';

interface CornerMastery {
  corner_id: number;
  mastery_score: number;
  grade: string;
  dimensions?: Record<string, number>;
}

interface MasteryData {
  overall_score: number;
  overall_grade: string;
  corners: CornerMastery[];
}

interface CornerMasteryCardProps {
  sessionId: string;
}

function gradeColor(grade: string): string {
  const g = grade.toUpperCase().charAt(0);
  switch (g) {
    case 'A':
      return 'text-green-400';
    case 'B':
      return 'text-amber-400';
    case 'C':
      return 'text-yellow-400';
    default:
      return 'text-red-400';
  }
}

function gradeBg(grade: string): string {
  const g = grade.toUpperCase().charAt(0);
  switch (g) {
    case 'A':
      return 'bg-green-400';
    case 'B':
      return 'bg-amber-400';
    case 'C':
      return 'bg-yellow-400';
    default:
      return 'bg-red-400';
  }
}

export function CornerMasteryCard({ sessionId }: CornerMasteryCardProps) {
  const [data, setData] = useState<MasteryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<MasteryData>(`/sessions/${sessionId}/corner-mastery`)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error)?.message ?? 'Failed to load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (loading) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4 animate-pulse">
        <div className="h-4 bg-asphalt rounded w-36 mb-3" />
        <div className="h-12 bg-asphalt rounded mb-3" />
        <div className="space-y-2">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-3 bg-asphalt rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4">
        <h3 className="text-sm text-chalk font-telemetry mb-2">Corner Mastery</h3>
        <p className="text-xs text-steel">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-concrete rounded-lg border border-steel/10 p-4">
        <h3 className="text-sm text-chalk font-telemetry mb-2">Corner Mastery</h3>
        <p className="text-xs text-steel">No mastery data available.</p>
      </div>
    );
  }

  return (
    <div className="bg-concrete rounded-lg border border-steel/10 p-4">
      <div className="mb-3">
        <h3 className="text-sm text-chalk font-telemetry">Corner Mastery</h3>
        <p className="text-[10px] text-steel/60 font-telemetry mt-0.5">
          Composite score: brake precision, apex speed, exit, consistency, grip
        </p>
      </div>

      {/* Overall grade + score */}
      <div className="flex items-center gap-3 mb-4">
        <span className={`text-4xl font-monument ${gradeColor(data.overall_grade)}`}>
          {data.overall_grade}
        </span>
        <div>
          <p className="text-chalk font-mono text-sm">{data.overall_score != null ? data.overall_score.toFixed(0) : '\u2014'}/100</p>
          <p className="text-steel text-[10px] font-telemetry uppercase">Overall Mastery</p>
        </div>
      </div>

      {/* Per-corner progress bars */}
      <div className="space-y-2">
        {data.corners.map((c) => (
          <div key={c.corner_id} className="flex items-center gap-2">
            <span className="text-[10px] text-steel font-mono w-6 shrink-0">
              C{c.corner_id}
            </span>
            <div className="flex-1 h-2 bg-asphalt rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${gradeBg(c.grade)}/60`}
                style={{ width: `${Math.max(0, Math.min(100, c.mastery_score))}%` }}
              />
            </div>
            <span className={`text-[10px] font-telemetry w-4 text-right ${gradeColor(c.grade)}`}>
              {c.grade}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
