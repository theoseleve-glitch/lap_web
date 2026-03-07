import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Breadcrumb } from '@/components/ui/Breadcrumb';

vi.mock('next/navigation', () => ({ usePathname: vi.fn() }));
import { usePathname } from 'next/navigation';
const mockUsePathname = vi.mocked(usePathname);

describe('Breadcrumb', () => {
  it('renders nothing for top-level pages', () => {
    mockUsePathname.mockReturnValue('/pricing');
    const { container } = render(<Breadcrumb />);
    expect(container.innerHTML).toBe('');
  });

  it('renders breadcrumb trail for subpages', () => {
    mockUsePathname.mockReturnValue('/pricing/compare');
    render(<Breadcrumb />);
    const nav = screen.getByRole('navigation', { name: /breadcrumb/i });
    expect(nav).toBeInTheDocument();
    expect(nav.querySelector('ol')).toBeInTheDocument();
    expect(nav.querySelectorAll('a').length).toBeGreaterThanOrEqual(1);
  });

  it('renders nothing for unknown paths', () => {
    mockUsePathname.mockReturnValue('/nonexistent/path');
    const { container } = render(<Breadcrumb />);
    expect(container.innerHTML).toBe('');
  });
});
