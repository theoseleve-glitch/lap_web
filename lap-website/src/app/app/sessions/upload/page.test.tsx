import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import userEvent from '@testing-library/user-event';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/app/sessions/upload',
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) =>
    // eslint-disable-next-line @next/next/no-html-link-for-pages
    <a href={href}>{children}</a>,
}));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQuery: () => ({ data: null, isLoading: false, error: null }),
  };
});

import UploadPageWrapper from './page';

describe('UploadPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true, data: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    );
  });

  it('accepts .csv, .txt and .ibt files', () => {
    render(<UploadPageWrapper />);
    const input = screen.getByLabelText(/choose telemetry files/i) as HTMLInputElement;
    expect(input.accept).toContain('.csv');
    expect(input.accept).toContain('.txt');
    expect(input.accept).toContain('.ibt');
  });

  it('shows heuristic source badge "iRacing" after selecting a .ibt file', async () => {
    render(<UploadPageWrapper />);
    const input = screen.getByLabelText(/choose telemetry files/i) as HTMLInputElement;
    const file = new File(['x'], 'lap.ibt', { type: 'application/octet-stream' });
    await userEvent.upload(input, file);
    expect(screen.getByText('iRacing')).toBeInTheDocument();
  });

  it('shows heuristic source badge "GPS" after selecting a .csv file', async () => {
    render(<UploadPageWrapper />);
    const input = screen.getByLabelText(/choose telemetry files/i) as HTMLInputElement;
    const file = new File(['x'], 'lap.csv', { type: 'text/csv' });
    await userEvent.upload(input, file);
    expect(screen.getByText('GPS')).toBeInTheDocument();
  });
});
