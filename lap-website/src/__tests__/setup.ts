import '@testing-library/jest-dom';
import { vi } from 'vitest';

// next/font/google uses a build-time SWC transform (font file generation +
// CSS injection) that doesn't run under vitest, so calling it directly
// throws "Inter is not a function" etc. Stub it with plain objects shaped
// like the real return value (`.variable` / `.className`) — src/app/layout.tsx
// is the only consumer (Inter, Space_Grotesk, Space_Mono).
vi.mock('next/font/google', () => {
  const mockFont = (name: string) => () => ({
    variable: `--font-${name}`,
    className: `font-${name}`,
  });
  return {
    Inter: mockFont('inter'),
    Space_Grotesk: mockFont('space-grotesk'),
    Space_Mono: mockFont('space-mono'),
  };
});
