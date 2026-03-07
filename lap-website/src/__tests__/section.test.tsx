import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Section } from '@/components/ui/Section';

describe('Section', () => {
  it('renders children', () => {
    render(<Section><p>Content here</p></Section>);
    expect(screen.getByText('Content here')).toBeInTheDocument();
  });
  it('renders h2 heading by default', () => {
    render(<Section heading="Features"><p>content</p></Section>);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Features');
  });
  it('renders h3 when level=3', () => {
    render(<Section heading="Sub Feature" level={3}><p>content</p></Section>);
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Sub Feature');
  });
  it('sets id on wrapper for anchor linking', () => {
    const { container } = render(<Section id="features" heading="Features"><p>x</p></Section>);
    expect(container.querySelector('#features')).toBeInTheDocument();
  });
  it('does not render heading when omitted', () => {
    render(<Section><p>No heading</p></Section>);
    expect(screen.queryByRole('heading')).toBeNull();
  });
});
