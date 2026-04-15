import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import Lap3DConceptPage, { metadata } from '@/app/concept/lap-3d-v1/page';

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

describe('lap-3d concept route', () => {
  it('marks the route as noindex', () => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
  });

  it('renders the four major narrative beats', () => {
    render(<Lap3DConceptPage />);

    expect(
      screen.getByRole('heading', { level: 1, name: /one lap\.\s*one decisive view\./i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /time disappears before teams can explain it\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /telemetry should move like a car, not a spreadsheet\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {
        level: 2,
        name: /the differentiator is not more data\. it is faster conviction\./i,
      }),
    ).toBeInTheDocument();
  });
});
