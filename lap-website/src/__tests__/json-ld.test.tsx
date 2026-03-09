import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { JsonLd } from '@/components/seo/JsonLd';

describe('JsonLd', () => {
  it('renders WebPage schema for a standard page', () => {
    const { container } = render(<JsonLd pathname="/product" />);
    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    const data = JSON.parse(script!.textContent!);
    expect(data['@graph'].some((s: Record<string, unknown>) => s['@type'] === 'WebPage')).toBe(true);
  });

  it('renders BreadcrumbList for subpages', () => {
    const { container } = render(<JsonLd pathname="/pricing/compare" />);
    const data = JSON.parse(
      container.querySelector('script[type="application/ld+json"]')!.textContent!,
    );
    expect(data['@graph'].some((s: Record<string, unknown>) => s['@type'] === 'BreadcrumbList')).toBe(true);
  });

  it('renders FAQPage schema when faqItems provided', () => {
    const { container } = render(
      <JsonLd pathname="/pricing" faqItems={[{ question: 'Q?', answer: 'A.' }]} />,
    );
    const data = JSON.parse(
      container.querySelector('script[type="application/ld+json"]')!.textContent!,
    );
    expect(data['@graph'].some((s: Record<string, unknown>) => s['@type'] === 'FAQPage')).toBe(true);
  });

  it('renders Article schema with article data', () => {
    const { container } = render(
      <JsonLd
        pathname="/insights"
        article={{ title: 'Test Article', datePublished: '2026-01-01', summary: 'Summary text' }}
      />,
    );
    const data = JSON.parse(
      container.querySelector('script[type="application/ld+json"]')!.textContent!,
    );
    expect(data['@graph'].some((s: Record<string, unknown>) => s['@type'] === 'Article')).toBe(true);
  });

  it('returns null for unknown paths', () => {
    const { container } = render(<JsonLd pathname="/nonexistent" />);
    expect(container.querySelector('script[type="application/ld+json"]')).toBeNull();
  });
});
