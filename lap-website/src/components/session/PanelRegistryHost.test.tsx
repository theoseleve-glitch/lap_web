import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { realLifeSession, iracingSession } from '@/mocks/fixtures';
import { PanelRegistryHost } from './PanelRegistryHost';

describe('PanelRegistryHost', () => {
  it('renders Coaching and Optimizer panels for real-life sessions', () => {
    render(<PanelRegistryHost {...realLifeSession} />);
    expect(screen.getByRole('heading', { name: /coaching/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /optimizer/i })).toBeInTheDocument();
  });

  it('renders both panels for iRacing sessions, with full-fidelity optimizer label', () => {
    render(<PanelRegistryHost {...iracingSession} />);
    expect(screen.getByRole('heading', { name: /coaching/i })).toBeInTheDocument();
    expect(screen.getByText(/full fidelity/i)).toBeInTheDocument();
  });
});
