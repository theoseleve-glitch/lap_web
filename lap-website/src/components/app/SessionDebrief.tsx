'use client';

interface CornerData {
  corner_number?: number;
  name?: string;
  coaching?: string;
  time_loss_s?: number | null;
  severity?: string;
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

interface LapData {
  lap_number: number;
  lap_time_s: number | null;
  is_valid: number;
  is_best: number;
}

interface SessionDebriefProps {
  totalScore: number | null;
  grade: string | null;
  scores: ScoreData | null;
  laps: LapData[];
  corners: CornerData[];
}

function fmtTime(s: number): string {
  if (s >= 60) {
    const m = Math.floor(s / 60);
    const sec = s - m * 60;
    return `${m}:${sec.toFixed(3).padStart(6, '0')}`;
  }
  return `${s.toFixed(3)}s`;
}

function buildSummary(totalScore: number | null, grade: string | null, scores: ScoreData | null): string {
  if (totalScore == null || !scores) return 'Score data unavailable for this session.';

  const parts: string[] = [`You scored ${Math.round(totalScore)}/100 (${grade || '?'} grade).`];

  if (scores.strengths?.length) {
    parts.push(`Your ${scores.strengths.join(' and ').toLowerCase()} ${scores.strengths.length === 1 ? 'was' : 'were'} standout.`);
  }
  if (scores.weaknesses?.length) {
    parts.push(`Focus on improving ${scores.weaknesses.join(' and ').toLowerCase()}.`);
  }

  return parts.join(' ');
}

function buildHighlights(laps: LapData[]): string[] {
  const validTimes = laps
    .filter((l) => l.is_valid && l.lap_time_s != null && l.lap_time_s > 0)
    .map((l) => l.lap_time_s!);

  if (validTimes.length === 0) return [];

  const best = Math.min(...validTimes);
  const mean = validTimes.reduce((a, b) => a + b, 0) / validTimes.length;
  const stddev = Math.sqrt(validTimes.reduce((a, t) => a + (t - mean) ** 2, 0) / validTimes.length);
  const cv = mean > 0 ? (stddev / mean) * 100 : 0;

  const highlights: string[] = [
    `Best lap: ${fmtTime(best)}`,
    `Consistency: ${cv.toFixed(1)}% variation across ${validTimes.length} laps`,
  ];

  // Top 25% average
  const sorted = [...validTimes].sort((a, b) => a - b);
  const top25Count = Math.max(1, Math.ceil(sorted.length * 0.25));
  const top25Avg = sorted.slice(0, top25Count).reduce((a, b) => a + b, 0) / top25Count;
  highlights.push(`Top 25% average: ${fmtTime(top25Avg)}`);

  return highlights;
}

function buildFocusAreas(corners: CornerData[]): { text: string; loss: number }[] {
  return corners
    .filter((c) => c.coaching && c.time_loss_s != null && c.time_loss_s > 0)
    .sort((a, b) => (b.time_loss_s ?? 0) - (a.time_loss_s ?? 0))
    .slice(0, 4)
    .map((c) => ({
      text: `${c.name || `Corner ${c.corner_number}`}: ${c.coaching} (+${c.time_loss_s!.toFixed(3)}s)`,
      loss: c.time_loss_s!,
    }));
}

function buildDrills(scores: ScoreData | null): string[] {
  if (!scores) return [];
  const drills: string[] = [];

  const consPct = scores.consistency_score != null && scores.consistency_max
    ? scores.consistency_score / scores.consistency_max
    : 1;
  if (consPct < 0.70) {
    drills.push('Consistency drill: 5 laps targeting same line and braking points');
  }

  const execPct = scores.execution_score != null && scores.execution_max
    ? scores.execution_score / scores.execution_max
    : 1;
  if (execPct < 0.70) {
    drills.push('Corner precision drill: focus on apex speed and exit throttle timing');
  }

  const robPct = scores.robustness_score != null && scores.robustness_max
    ? scores.robustness_score / scores.robustness_max
    : 1;
  if (robPct < 0.70) {
    drills.push('Endurance stint: 10+ lap run maintaining pace within 0.5% of best');
  }

  if (drills.length === 0) {
    drills.push('Continue refining your technique — focus on your weakest corner');
  }

  return drills;
}

export function SessionDebrief({ totalScore, grade, scores, laps, corners }: SessionDebriefProps) {
  const summary = buildSummary(totalScore, grade, scores);
  const highlights = buildHighlights(laps);
  const focusAreas = buildFocusAreas(corners);
  const drills = buildDrills(scores);

  if (!scores && totalScore == null) return null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-6">
      <h2 className="text-lg font-monument text-chalk mb-4">Session Debrief</h2>

      {/* Performance Summary */}
      <div className="mb-4">
        <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Performance Summary</h3>
        <p className="text-sm text-chalk/90 font-body leading-relaxed">{summary}</p>
      </div>

      {/* Key Highlights */}
      {highlights.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Key Highlights</h3>
          <ul className="space-y-1">
            {highlights.map((h, i) => (
              <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
                <span className="text-acid-green shrink-0">*</span>
                {h}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Focus Areas */}
      {focusAreas.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Focus Areas</h3>
          <ul className="space-y-1">
            {focusAreas.map((f, i) => (
              <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
                <span className="text-marshal-yellow shrink-0">!</span>
                {f.text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Next Session Plan */}
      <div>
        <h3 className="text-xs text-steel font-body uppercase tracking-wider mb-2">Next Session Plan</h3>
        <ol className="space-y-1">
          {drills.map((d, i) => (
            <li key={i} className="text-sm text-chalk/80 font-body flex gap-2">
              <span className="text-cyan-400 shrink-0 font-telemetry">{i + 1}.</span>
              {d}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
