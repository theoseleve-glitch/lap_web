/**
 * scoring-weights.ts — Custom scoring weight preferences.
 *
 * Lets users adjust relative importance of the 4 scoring dimensions.
 * Default: all equal at 25 (total /100). Stored in localStorage.
 * The weighted total is computed client-side from raw sub-scores.
 */
import { create } from 'zustand';

export interface ScoringWeights {
  pace: number;
  consistency: number;
  execution: number;
  robustness: number;
}

interface ScoringWeightsStore extends ScoringWeights {
  setWeight: (key: keyof ScoringWeights, value: number) => void;
  reset: () => void;
}

const DEFAULT_WEIGHTS: ScoringWeights = {
  pace: 25,
  consistency: 25,
  execution: 25,
  robustness: 25,
};

const STORAGE_KEY = 'scoring_weights';

function loadWeights(): ScoringWeights {
  if (typeof window === 'undefined') return { ...DEFAULT_WEIGHTS };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ScoringWeights>;
      return {
        pace: typeof parsed.pace === 'number' ? parsed.pace : 25,
        consistency: typeof parsed.consistency === 'number' ? parsed.consistency : 25,
        execution: typeof parsed.execution === 'number' ? parsed.execution : 25,
        robustness: typeof parsed.robustness === 'number' ? parsed.robustness : 25,
      };
    }
  } catch {}
  return { ...DEFAULT_WEIGHTS };
}

function saveWeights(w: ScoringWeights) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(w)); } catch {}
}

export const useScoringWeights = create<ScoringWeightsStore>((set, get) => ({
  ...loadWeights(),
  setWeight: (key, value) => {
    const clamped = Math.max(0, Math.min(100, value));
    set({ [key]: clamped });
    const state = get();
    saveWeights({ pace: state.pace, consistency: state.consistency, execution: state.execution, robustness: state.robustness });
  },
  reset: () => {
    set({ ...DEFAULT_WEIGHTS });
    saveWeights(DEFAULT_WEIGHTS);
  },
}));

/**
 * Compute a weighted total score from raw sub-scores.
 * Sub-scores are assumed to be out of their respective max values (typically 25 each).
 */
export function computeWeightedTotal(
  scores: {
    pace_score: number | null;
    pace_max: number | null;
    consistency_score: number | null;
    consistency_max: number | null;
    execution_score: number | null;
    execution_max: number | null;
    robustness_score: number | null;
    robustness_max: number | null;
  },
  weights: ScoringWeights,
): number | null {
  const dims = [
    { score: scores.pace_score, max: scores.pace_max, weight: weights.pace },
    { score: scores.consistency_score, max: scores.consistency_max, weight: weights.consistency },
    { score: scores.execution_score, max: scores.execution_max, weight: weights.execution },
    { score: scores.robustness_score, max: scores.robustness_max, weight: weights.robustness },
  ];

  let totalWeight = 0;
  let totalWeighted = 0;

  for (const d of dims) {
    if (d.score == null || d.max == null || d.max === 0) continue;
    const normalized = d.score / d.max; // 0..1
    totalWeighted += normalized * d.weight;
    totalWeight += d.weight;
  }

  if (totalWeight === 0) return null;
  return (totalWeighted / totalWeight) * 100;
}
