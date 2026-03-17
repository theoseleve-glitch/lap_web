import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { SuccessPage } from '@/components/site/SuccessPage';
import { changelog } from '@/data/changelog';
import { footerLinks } from '@/data/navigation';
import { trackDemoCtaClick, trackDemoFormView } from '@/lib/analytics';

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

describe('SuccessPage template', () => {
  it('renders title, summary, next steps, and actions', () => {
    render(
      <SuccessPage
        title="Demo confirmed"
        summary="We will reach out within 24 hours."
        nextSteps={['Check email', 'Prepare CSV', 'Join call']}
        actions={[
          { label: 'Start Free', href: '/register?source=thank-you', primary: true },
          { label: 'Pricing', href: '/pricing' },
        ]}
      />,
    );

    expect(screen.getByText('Demo confirmed')).toBeInTheDocument();
    expect(screen.getByText('We will reach out within 24 hours.')).toBeInTheDocument();
    expect(screen.getByText('Check email')).toBeInTheDocument();
    expect(screen.getByText('Prepare CSV')).toBeInTheDocument();
    expect(screen.getByText('Join call')).toBeInTheDocument();
    expect(screen.getByText('Start Free')).toHaveAttribute('href', '/register?source=thank-you');
    expect(screen.getByText('Pricing')).toHaveAttribute('href', '/pricing');
  });

  it('renders default support note', () => {
    render(
      <SuccessPage
        title="Thanks"
        summary="Done."
        nextSteps={[]}
        actions={[{ label: 'Home', href: '/' }]}
      />,
    );
    expect(screen.getByText(/contact@lap-coach.racing/)).toBeInTheDocument();
  });

  it('renders custom support note', () => {
    render(
      <SuccessPage
        title="Thanks"
        summary="Done."
        nextSteps={[]}
        actions={[{ label: 'Home', href: '/' }]}
        supportNote="Call us at +1-555-0100"
      />,
    );
    expect(screen.getByText('Call us at +1-555-0100')).toBeInTheDocument();
  });

  it('uses consistent structure across form types', () => {
    const types = ['contact', 'demo', 'book', 'waitlist'] as const;
    for (const type of types) {
      const { unmount } = render(
        <SuccessPage
          title={`${type} success`}
          summary={`${type} received`}
          nextSteps={['Step 1', 'Step 2']}
          actions={[{ label: 'Continue', href: '/', primary: true }]}
        />,
      );
      expect(screen.getByText(`${type} success`)).toBeInTheDocument();
      expect(screen.getByText('Next Steps')).toBeInTheDocument();
      expect(screen.getByText('Continue')).toBeInTheDocument();
      unmount();
    }
  });
});

describe('Changelog data', () => {
  it('has at least one entry', () => {
    expect(changelog.length).toBeGreaterThan(0);
  });

  it('entries have required fields', () => {
    for (const entry of changelog) {
      expect(entry.version).toBeTruthy();
      expect(entry.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(entry.tags.length).toBeGreaterThan(0);
      expect(entry.summary).toBeTruthy();
    }
  });

  it('entries are in reverse chronological order', () => {
    for (let i = 1; i < changelog.length; i++) {
      expect(changelog[i - 1].date >= changelog[i].date).toBe(true);
    }
  });
});

describe('Navigation links', () => {
  it('footer includes Help link', () => {
    expect(footerLinks.find((l) => l.href === '/help')).toBeTruthy();
  });

  it('footer includes Changelog link', () => {
    expect(footerLinks.find((l) => l.href === '/changelog')).toBeTruthy();
  });

  it('footer includes Demo link', () => {
    expect(footerLinks.find((l) => l.href === '/demo')).toBeTruthy();
  });
});

describe('Demo funnel tracking events', () => {
  it('trackDemoCtaClick is a function', () => {
    expect(typeof trackDemoCtaClick).toBe('function');
  });

  it('trackDemoFormView is a function', () => {
    expect(typeof trackDemoFormView).toBe('function');
  });
});
