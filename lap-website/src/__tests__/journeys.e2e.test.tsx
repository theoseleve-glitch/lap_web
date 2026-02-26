import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { LeadForm } from '@/components/forms/LeadForm';
import { PricingTable } from '@/components/ui/PricingTable';
import { b2cPlans } from '@/data/pricing';

const pushMock = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => '/demo',
  useSearchParams: () => new URLSearchParams('persona=drivers'),
}));

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe('Key conversion journeys', () => {
  beforeEach(() => {
    pushMock.mockReset();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('demo booking journey submits and redirects to thank-you', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, message: 'ok' }),
    } as Response);

    render(<LeadForm type="demo" submitLabel="Request Demo" />);

    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Jane Driver' },
    });
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'jane@example.com' },
    });
    fireEvent.change(screen.getByLabelText('Company'), {
      target: { value: 'Apex Team' },
    });

    fireEvent.submit(screen.getByRole('button', { name: 'Request Demo' }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/leads',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith('/thank-you/demo');
    });
  });

  it('contact submit journey surfaces error state on API failure', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      json: async () => ({ ok: false, message: 'Lead endpoint unavailable' }),
    } as Response);

    render(<LeadForm type="contact" submitLabel="Send Message" />);

    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Race Ops' },
    });
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'ops@example.com' },
    });
    fireEvent.change(screen.getByLabelText('Company'), {
      target: { value: 'Circuit Team' },
    });
    fireEvent.change(screen.getByLabelText('How can we help?'), {
      target: { value: 'Need enterprise onboarding' },
    });

    fireEvent.submit(screen.getByRole('button', { name: 'Send Message' }));

    await waitFor(() => {
      expect(screen.getByText('Lead endpoint unavailable')).toBeInTheDocument();
    });
    expect(pushMock).not.toHaveBeenCalled();
  });

  it('pricing CTA points to a real booking route', () => {
    render(<PricingTable plans={b2cPlans} billingPeriod="annual" />);
    const cta = screen.getByRole('link', { name: 'Upgrade' });
    expect(cta).toHaveAttribute('href', '/book?plan=PERFORMANCE');
  });
});
