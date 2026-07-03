import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ScoreTiers } from '@/components/app/ScoreTiers';

const tiers = {
  absolute: { total_score: 80, grade: 'A', sub_scores: {} },
  contextualized: {
    total_score: 68,
    grade: 'B',
    adjustments: [{ code: 'DNF_ROBUSTNESS_ZERO', label: 'DNF — robustness 0', dimension: 'robustness', delta: -12 }],
    provenance: [],
  },
  competition: {
    score: 70, grade: 'B', position: 3, total_competitors: 12, percentile: 81.8,
    is_dnf: false, basis: 'session_competitors_self_reported',
    provenance: [{ code: 'SELF_REPORTED', label: 'Self-reported', dimension: null }],
  },
  reflection_present: true,
};

describe('ScoreTiers', () => {
  it('renders all three tier totals', () => {
    render(<ScoreTiers tiers={tiers} />);
    expect(screen.getByText('80')).toBeInTheDocument();
    expect(screen.getByText('68')).toBeInTheDocument();
    expect(screen.getByText('70')).toBeInTheDocument();
  });

  it('shows the contextual adjustment reason', () => {
    render(<ScoreTiers tiers={tiers} />);
    expect(screen.getByText(/DNF — robustness 0/)).toBeInTheDocument();
  });

  it('labels competition as self-reported', () => {
    render(<ScoreTiers tiers={tiers} />);
    expect(screen.getByText(/Self-reported/)).toBeInTheDocument();
  });

  it('hides competition card when null', () => {
    render(<ScoreTiers tiers={{ ...tiers, competition: null }} />);
    expect(screen.queryByText('vs Competition')).not.toBeInTheDocument();
  });
});
