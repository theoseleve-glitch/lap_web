import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CornerReplayControls } from '../CornerReplayControls';
import { mockCornerReplayResponse } from './fixtures';

const defaultProps = {
  mode: 'review' as const,
  corners: mockCornerReplayResponse.corners,
  cornerIndex: 0,
  laps: mockCornerReplayResponse.laps,
  lapA: 1,
  lapB: 2,
  frame: 0,
  totalFrames: 60,
  playing: false,
  speed: 1 as const,
  onModeChange: vi.fn(),
  onCornerChange: vi.fn(),
  onPrevCorner: vi.fn(),
  onNextCorner: vi.fn(),
  onLapAChange: vi.fn(),
  onLapBChange: vi.fn(),
  onScrub: vi.fn(),
  onTogglePlay: vi.fn(),
  onSpeedChange: vi.fn(),
};

describe('CornerReplayControls', () => {
  it('renders mode tabs', () => {
    render(<CornerReplayControls {...defaultProps} />);
    expect(screen.getByText('Review')).toBeDefined();
    expect(screen.getByText('Split')).toBeDefined();
    expect(screen.getByText('Top 3')).toBeDefined();
  });

  it('renders corner pills', () => {
    render(<CornerReplayControls {...defaultProps} />);
    expect(screen.getByText('Turn 1')).toBeDefined();
    expect(screen.getByText('Hairpin')).toBeDefined();
    expect(screen.getByText('Chicane')).toBeDefined();
  });

  it('hides lap selectors in review mode', () => {
    render(<CornerReplayControls {...defaultProps} mode="review" />);
    expect(screen.queryByText('Lap A')).toBeNull();
  });

  it('shows lap selectors in split mode', () => {
    render(<CornerReplayControls {...defaultProps} mode="split" />);
    expect(screen.getByText('Lap A')).toBeDefined();
    expect(screen.getByText('Lap B')).toBeDefined();
  });

  it('calls onModeChange when mode tab clicked', () => {
    const fn = vi.fn();
    render(<CornerReplayControls {...defaultProps} onModeChange={fn} />);
    fireEvent.click(screen.getByText('Split'));
    expect(fn).toHaveBeenCalledWith('split');
  });

  it('renders speed buttons', () => {
    render(<CornerReplayControls {...defaultProps} />);
    expect(screen.getByText('0.25x')).toBeDefined();
    expect(screen.getByText('1x')).toBeDefined();
    expect(screen.getByText('2x')).toBeDefined();
  });
});
