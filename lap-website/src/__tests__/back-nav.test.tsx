import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BackNav } from '@/components/ui/BackNav';

describe('BackNav', () => {
  it('renders link with default label', () => {
    render(<BackNav href="/app/dashboard" />);
    const link = screen.getByRole('link', { name: /back/i });
    expect(link).toHaveAttribute('href', '/app/dashboard');
    expect(link).toHaveTextContent('Back');
  });
  it('renders custom label', () => {
    render(<BackNav href="/app" label="Back to App" />);
    expect(screen.getByRole('link', { name: /back to app/i })).toBeInTheDocument();
  });
});
