import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Lap3DConceptV2Page, { metadata } from '@/app/concept/lap-3d-v2/page';

vi.mock('next/dynamic', () => ({
  __esModule: true,
  default: () => {
    const DynamicMock = () => <div data-testid="lap-3d-world" />;
    return DynamicMock;
  },
}));

vi.mock('@/hooks/useReducedMotion', () => ({
  useReducedMotion: () => ({
    reducedMotion: false,
    toggle: vi.fn(),
    userToggled: false,
  }),
}));

vi.mock('@/lib/gsap-config', () => ({
  registerGsap: vi.fn(),
}));

vi.mock('gsap', () => {
  const timeline = {
    fromTo: vi.fn().mockReturnThis(),
    to: vi.fn().mockReturnThis(),
  };

  return {
    gsap: {
      registerPlugin: vi.fn(),
      set: vi.fn(),
      fromTo: vi.fn(),
      timeline: vi.fn(() => timeline),
      context: (callback: () => void) => {
        callback();
        return { revert: vi.fn() };
      },
      utils: {
        toArray: vi.fn(() => []),
      },
    },
  };
});

vi.mock('gsap/ScrollTrigger', () => ({
  ScrollTrigger: {
    create: vi.fn(),
  },
}));

describe('lap-3d concept v2 route', () => {
  it('marks the route as noindex', () => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
  });

  it('renders the six major narrative beats', () => {
    render(<Lap3DConceptV2Page />);

    expect(
      screen.getByRole('heading', { level: 1, name: /hidden speed\.\s*revealed in one lap\./i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /the lap loses time before the eye notices\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /telemetry pipeline, not a process diagram\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /the data becomes coaching while the car is still alive\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /designed like an instrument, not a dashboard\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /choose the direction worth productionizing\./i,
      }),
    ).toBeInTheDocument();
  });
});
