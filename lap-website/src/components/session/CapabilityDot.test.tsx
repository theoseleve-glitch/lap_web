import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { CapabilityDots } from './CapabilityDot';

describe('CapabilityDots', () => {
  it('renders one dot per channel with accessible tooltip', () => {
    render(<CapabilityDots channels={['gps', 'throttle', 'brake']} />);
    expect(screen.getByLabelText(/channel: gps/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/channel: throttle/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/channel: brake/i)).toBeInTheDocument();
  });

  it('renders nothing when channels empty', () => {
    const { container } = render(<CapabilityDots channels={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
