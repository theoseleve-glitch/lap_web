import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { SourceBadge } from './SourceBadge';

describe('SourceBadge', () => {
  it('renders "GPS" for real_life', () => {
    render(<SourceBadge source="real_life" />);
    expect(screen.getByText('GPS')).toBeInTheDocument();
  });

  it('renders "iRacing" for iracing', () => {
    render(<SourceBadge source="iracing" />);
    expect(screen.getByText('iRacing')).toBeInTheDocument();
  });

  it('renders "AC" for ac', () => {
    render(<SourceBadge source="ac" />);
    expect(screen.getByText('AC')).toBeInTheDocument();
  });

  it('renders nothing when source is null', () => {
    const { container } = render(<SourceBadge source={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
