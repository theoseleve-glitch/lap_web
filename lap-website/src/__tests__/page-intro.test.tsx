import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PageIntro } from '@/components/ui/PageIntro';

describe('PageIntro', () => {
  it('renders exactly one h1', () => {
    render(<PageIntro title="Test Title" />);
    const headings = screen.getAllByRole('heading', { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent('Test Title');
  });
  it('renders subtitle when provided', () => {
    render(<PageIntro title="Title" subtitle="A subtitle" />);
    expect(screen.getByText('A subtitle')).toBeInTheDocument();
  });
  it('renders eyebrow when provided', () => {
    render(<PageIntro title="Title" eyebrow="Plans" />);
    expect(screen.getByText('Plans')).toBeInTheDocument();
  });
  it('renders badge when provided', () => {
    render(<PageIntro title="Title" badge="Beta" />);
    expect(screen.getByText('Beta')).toBeInTheDocument();
  });
  it('renders actions slot', () => {
    render(<PageIntro title="Title" actions={<button>Upload</button>} />);
    expect(screen.getByRole('button', { name: 'Upload' })).toBeInTheDocument();
  });
  it('does not render eyebrow/subtitle when omitted', () => {
    const { container } = render(<PageIntro title="Title" />);
    expect(container.querySelectorAll('p')).toHaveLength(0);
  });
});
