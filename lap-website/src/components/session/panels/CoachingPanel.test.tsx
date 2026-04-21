import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { realLifeSession, iracingSession } from '@/mocks/fixtures';
import { CoachingPanel } from './CoachingPanel';

describe('CoachingPanel', () => {
  it('renders the storyline headlines and global focus items', () => {
    render(<CoachingPanel {...realLifeSession} optimizer={null} />);
    expect(screen.getByText(/late braking at turn 3/i)).toBeInTheDocument();
    expect(screen.getByText(/brake earlier into t3/i)).toBeInTheDocument();
  });

  it('shows a "limited depth" note when input channels are absent', () => {
    render(<CoachingPanel {...realLifeSession} optimizer={null} />);
    expect(screen.getByText(/deeper input-aware coaching/i)).toBeInTheDocument();
  });

  it('does NOT show the "limited depth" note when inputs are present', () => {
    render(<CoachingPanel {...iracingSession} optimizer={null} />);
    expect(screen.queryByText(/deeper input-aware coaching/i)).toBeNull();
  });

  it('renders a friendly empty state when coaching contract is null', () => {
    render(<CoachingPanel session={realLifeSession.session} coaching={null} optimizer={null} />);
    expect(screen.getByText(/coaching not available/i)).toBeInTheDocument();
  });
});
