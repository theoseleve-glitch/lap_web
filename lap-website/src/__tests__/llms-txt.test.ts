import { describe, it, expect } from 'vitest';

describe('llms.txt route', () => {
  it('returns text/plain with correct header structure', async () => {
    const { GET } = await import('@/app/llms.txt/route');
    const response = GET();
    const text = await response.text();
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(text).toMatch(/^# LAP/);
    expect(text).toContain('> ');
    expect(text).toContain('## About');
    expect(text).toContain('## Key Pages');
    expect(text).toContain('## Canonical');
  });
});

describe('llms-full.txt route', () => {
  it('returns text/plain with FAQ and pricing content', async () => {
    const { GET } = await import('@/app/llms-full.txt/route');
    const response = GET();
    const text = await response.text();
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(text).toContain('## FAQ');
    expect(text).toContain('## Pricing');
    expect(text).toContain('## Glossary');
    expect(new TextEncoder().encode(text).length).toBeLessThan(100_000);
  });
});
