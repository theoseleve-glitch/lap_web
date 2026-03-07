import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppFooter } from '@/components/ui/AppFooter';

describe('AppFooter', () => {
  it('renders all four legal links', () => {
    render(<AppFooter />);
    expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/privacy');
    expect(screen.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
    expect(screen.getByRole('link', { name: 'Security' })).toHaveAttribute('href', '/security');
    expect(screen.getByRole('link', { name: 'Status' })).toHaveAttribute('href', '/status');
  });
  it('renders as a footer element', () => {
    render(<AppFooter />);
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });
});
