'use client';

import { chartColor } from '@/components/shared/chart-kit';

interface CornerData {
  corner_id: number;
  available: boolean;
  direction?: 'L' | 'R';
  coaching_hint?: string | null;
  time_loss_total_s?: number | null;
}

interface ScoreData {
  pace_score: number | null;
  pace_max: number | null;
  consistency_score: number | null;
  consistency_max: number | null;
  execution_score: number | null;
  execution_max: number | null;
  robustness_score: number | null;
  robustness_max: number | null;
  adaptation_score: number | null;
  strengths: string[];
  weaknesses: string[];
}

interface Drill {
  title: string;
  description: string;
  target: string;
  color: string;
}

interface DevelopmentDrillsProps {
  scores: ScoreData | null;
  corners: CornerData[];
  className?: string;
}

function findWorstCorner(corners: CornerData[]): CornerData | null {
  const ranked = corners
    .filter((c) => c.available && c.time_loss_total_s != null && c.time_loss_total_s > 0)
    .sort((a, b) => (b.time_loss_total_s ?? 0) - (a.time_loss_total_s ?? 0));
  return ranked[0] ?? null;
}

function cornerLabel(c: CornerData): string {
  return `Corner ${c.corner_id}${c.direction ? ` (${c.direction})` : ''}`;
}

function buildDrills(scores: ScoreData | null, corners: CornerData[]): Drill[] {
  const drills: Drill[] = [];
  const worst = findWorstCorner(corners);
  const worstLabel = worst ? cornerLabel(worst) : 'your weakest corner';

  if (!scores) {
    drills.push({
      title: 'Baseline Run',
      description: 'Drive 10 clean laps focusing on smooth inputs to establish your baseline.',
      target: 'All corners',
      color: chartColor.palette[3],
    });
    return drills;
  }

  const weaknesses = scores.weaknesses ?? [];

  if (weaknesses.includes('consistency')) {
    drills.push({
      title: 'Consistency Drill',
      description: `Repeat the same braking point for ${worstLabel} across 5 laps. Focus on hitting the same marks every time.`,
      target: worstLabel,
      color: chartColor.series.warning,
    });
  }

  if (weaknesses.includes('pace')) {
    const delta = worst?.time_loss_total_s ? `(${worst.time_loss_total_s.toFixed(2)}s lost here)` : '';
    drills.push({
      title: 'Pace Attack',
      description: `Attack ${worstLabel} more aggressively ${delta}. Gradually increase corner entry speed over 3-5 laps.`,
      target: worstLabel,
      color: chartColor.series.negative,
    });
  }

  if (weaknesses.includes('execution')) {
    drills.push({
      title: 'Throttle Precision',
      description: `Focus on smooth throttle application through ${worstLabel}. Progressive roll-on, no sudden inputs.`,
      target: worstLabel,
      color: chartColor.series.positive,
    });
  }

  if (weaknesses.includes('robustness')) {
    drills.push({
      title: 'Endurance Stint',
      description: 'Complete 10 clean laps without invalid markers. Focus on maintaining pace within 0.5% of your best.',
      target: 'Full circuit',
      color: chartColor.series.reference,
    });
  }

  // Always add a generic drill if we have fewer than 3
  if (drills.length < 3) {
    const consPct = scores.consistency_score != null && scores.consistency_max
      ? scores.consistency_score / scores.consistency_max
      : 1;
    if (consPct < 0.85 && !weaknesses.includes('consistency')) {
      drills.push({
        title: 'Line Refinement',
        description: `Repeat 5 laps targeting identical racing line through ${worstLabel}. Same turn-in, apex, exit every lap.`,
        target: worstLabel,
        color: chartColor.palette[5],
      });
    }
  }

  if (drills.length === 0) {
    drills.push({
      title: 'Technique Polish',
      description: `Drive 10 clean laps focusing on smooth inputs. Target your weakest corner: ${worstLabel}.`,
      target: worstLabel,
      color: chartColor.palette[3],
    });
  }

  return drills.slice(0, 5);
}

export function DevelopmentDrills({ scores, corners, className = '' }: DevelopmentDrillsProps) {
  const drills = buildDrills(scores, corners);

  return (
    <div className={className}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {drills.map((drill, i) => (
          <div
            key={i}
            className="bg-asphalt/50 rounded-lg border border-steel/10 p-4 flex flex-col"
          >
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: drill.color }}
              />
              <h4 className="text-sm font-monument text-chalk">{drill.title}</h4>
            </div>
            <p className="text-xs text-chalk/70 font-body leading-relaxed flex-1">
              {drill.description}
            </p>
            <div className="mt-3 text-xs text-steel font-telemetry">
              Target: {drill.target}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
