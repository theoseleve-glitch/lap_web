import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SectionTabs } from '@/components/ui/SectionTabs';

beforeAll(() => {
  global.IntersectionObserver = class IntersectionObserver {
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof globalThis.IntersectionObserver;
});

vi.mock('next/navigation', () => ({ usePathname: vi.fn() }));
import { usePathname } from 'next/navigation';
const mockUsePathname = vi.mocked(usePathname);

describe('SectionTabs', () => {
  it('renders nothing when route has no sectionAnchors', () => {
    mockUsePathname.mockReturnValue('/contact');
    const { container } = render(<SectionTabs />);
    expect(container.querySelector('nav')).toBeNull();
  });
  it('renders tabs for routes with sectionAnchors', () => {
    mockUsePathname.mockReturnValue('/pricing');
    render(<SectionTabs />);
    const nav = screen.getByRole('navigation', { name: /page sections/i });
    expect(nav).toBeInTheDocument();
    expect(nav.querySelectorAll('a').length).toBeGreaterThanOrEqual(2);
  });
  it('renders nothing for unknown routes', () => {
    mockUsePathname.mockReturnValue('/nonexistent');
    const { container } = render(<SectionTabs />);
    expect(container.querySelector('nav')).toBeNull();
  });
  it('each tab links to anchor', () => {
    mockUsePathname.mockReturnValue('/pricing');
    render(<SectionTabs />);
    const nav = screen.getByRole('navigation', { name: /page sections/i });
    for (const link of nav.querySelectorAll('a')) {
      expect(link.getAttribute('href')).toMatch(/^#/);
    }
  });
});
