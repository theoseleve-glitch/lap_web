import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { realLifeSession, iracingSession } from '@/mocks/fixtures';
import { OptimizerPanel } from './OptimizerPanel';

describe('OptimizerPanel', () => {
  it('renders theoretical lap time and time loss for trajectory_only sessions', () => {
    render(<OptimizerPanel {...realLifeSession} coaching={null} />);
    expect(screen.getByText(/trajectory-only/i)).toBeInTheDocument();
    expect(screen.getByText(/51\.35s/)).toBeInTheDocument();
    expect(screen.getByText(/0\.57s/)).toBeInTheDocument();
  });

  it('renders input trace summary for full_fidelity sessions', () => {
    render(<OptimizerPanel {...iracingSession} coaching={null} />);
    expect(screen.getByText(/full fidelity/i)).toBeInTheDocument();
    expect(screen.getByTestId('reconstructed-inputs-summary')).toBeInTheDocument();
    expect(screen.getByText(/throttle trail/i)).toBeInTheDocument();
  });

  it('does NOT render input trace when depth is trajectory_only', () => {
    render(<OptimizerPanel {...realLifeSession} coaching={null} />);
    expect(screen.queryByTestId('reconstructed-inputs-summary')).toBeNull();
  });

  it('renders "not available" when optimizer contract is null', () => {
    render(<OptimizerPanel session={realLifeSession.session} coaching={null} optimizer={null} />);
    expect(screen.getByText(/optimizer not available/i)).toBeInTheDocument();
  });
});
