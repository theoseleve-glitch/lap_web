/**
 * Frontend optimal-line data contract (sub-project C honesty layer): the
 * racing line must be drawn ONLY when the backend's honesty verdict is
 * exactly `tier === 'optimal_line'` with `drawable === true`. Previously
 * TrackSurfacePanel hardcoded `showOptimalLine={false}` — safe, but not
 * driven by the data contract, so a genuinely honesty-approved line could
 * never display either. These tests exercise the render gate directly,
 * mocking useTrackSurfaceData so no network/query-client setup is needed.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import TrackSurfacePanel from '@/components/app/track-surface/TrackSurfacePanel';

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
}));

const mockUseTrackSurfaceData = vi.fn();
vi.mock('@/components/app/track-surface/useTrackSurfaceData', () => ({
  useTrackSurfaceData: (...args: unknown[]) => mockUseTrackSurfaceData(...args),
}));

// Stub out the Three.js/react-three-fiber renderer entirely — the render
// gate under test is TrackSurfacePanel's `showOptimalLine` prop, not the
// WebGL scene graph. The stub just surfaces the prop it received so the
// test can assert on it directly.
vi.mock('@/components/app/track-surface/TrackSurface3D', () => ({
  TrackSurface3D: (props: { showOptimalLine?: boolean }) => (
    <div
      data-testid="track-surface-3d"
      data-show-optimal-line={String(!!props.showOptimalLine)}
    >
      {props.showOptimalLine && (
        <div data-testid="optimal-line-mesh">optimal line drawn</div>
      )}
    </div>
  ),
  isGripAvailable: () => true,
  gradientProfile: () => ({ sSorted: [], gPerBin: [], G: 0.1 }),
}));

function baseHookReturn(overrides: Record<string, unknown> = {}) {
  return {
    surface: null,
    isLoading: false,
    optimalLine: null,
    gpsTrace: null,
    lineDelta: null,
    error: null,
    optimalLineDrawable: undefined,
    optimalLineTier: null,
    optimalLineReason: null,
    ...overrides,
  };
}

describe('TrackSurfacePanel — optimal-line honesty render gate', () => {
  beforeEach(() => {
    mockUseTrackSurfaceData.mockReset();
  });

  it('draws the optimal line when drawable:true and tier is exactly optimal_line', () => {
    mockUseTrackSurfaceData.mockReturnValue(
      baseHookReturn({
        optimalLineDrawable: true,
        optimalLineTier: 'optimal_line',
        optimalLineReason: null,
      }),
    );

    render(<TrackSurfacePanel sessionId="sess-1" />);

    expect(screen.getByTestId('track-surface-3d')).toHaveAttribute(
      'data-show-optimal-line',
      'true',
    );
    expect(screen.getByTestId('optimal-line-mesh')).toBeInTheDocument();
    // No "why not" affordance when the line is actually drawn (all of its
    // copy variants start with "Racing line ..."; the mesh stub's own text
    // is deliberately worded differently so this assertion can't collide).
    expect(screen.queryByText(/racing line/i)).not.toBeInTheDocument();
  });

  it('withholds the line and shows the tier/reason affordance when drawable:false', () => {
    mockUseTrackSurfaceData.mockReturnValue(
      baseHookReturn({
        optimalLineDrawable: false,
        optimalLineTier: 'speed_profile_only',
        optimalLineReason: 'Grip confidence below the honesty floor for this track.',
      }),
    );

    render(<TrackSurfacePanel sessionId="sess-1" />);

    expect(screen.getByTestId('track-surface-3d')).toHaveAttribute(
      'data-show-optimal-line',
      'false',
    );
    expect(screen.queryByTestId('optimal-line-mesh')).not.toBeInTheDocument();
    expect(
      screen.getByText('Grip confidence below the honesty floor for this track.'),
    ).toBeInTheDocument();
  });

  it('fails safe (no line) when drawable is missing/undefined', () => {
    mockUseTrackSurfaceData.mockReturnValue(
      baseHookReturn({
        optimalLineDrawable: undefined,
        optimalLineTier: null,
        optimalLineReason: null,
      }),
    );

    render(<TrackSurfacePanel sessionId="sess-1" />);

    expect(screen.getByTestId('track-surface-3d')).toHaveAttribute(
      'data-show-optimal-line',
      'false',
    );
    expect(screen.queryByTestId('optimal-line-mesh')).not.toBeInTheDocument();
    // The default fallback message still renders — the affordance never
    // goes silent just because the data is missing rather than degraded.
    expect(
      screen.getByText('Racing line not yet available for this track.'),
    ).toBeInTheDocument();
  });

  it('defense-in-depth: a non-optimal tier never draws even if drawable is erroneously true-ish', () => {
    mockUseTrackSurfaceData.mockReturnValue(
      baseHookReturn({
        optimalLineDrawable: true,
        optimalLineTier: 'speed_profile_only',
        optimalLineReason: null,
      }),
    );

    render(<TrackSurfacePanel sessionId="sess-1" />);

    expect(screen.getByTestId('track-surface-3d')).toHaveAttribute(
      'data-show-optimal-line',
      'false',
    );
    expect(screen.queryByTestId('optimal-line-mesh')).not.toBeInTheDocument();
    // Falls back to the tier-keyed copy since no explicit reason was sent.
    expect(
      screen.getByText('Racing line not yet available — speed profile only.'),
    ).toBeInTheDocument();
  });
});
