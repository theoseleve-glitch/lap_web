import { describe, it, expect } from 'vitest';
import { getSafeRedirect } from './safe-redirect';

describe('getSafeRedirect', () => {
  it('keeps a plain same-origin path', () => {
    expect(getSafeRedirect('/app/x')).toBe('/app/x');
  });

  it('keeps a legit deep path with a query string', () => {
    expect(getSafeRedirect('/app/sessions/123?tab=laps&sort=desc')).toBe(
      '/app/sessions/123?tab=laps&sort=desc',
    );
  });

  it('falls back for a protocol-relative URL', () => {
    expect(getSafeRedirect('//evil.com')).toBe('/app/dashboard');
  });

  it('falls back for an absolute https URL', () => {
    expect(getSafeRedirect('https://evil.com')).toBe('/app/dashboard');
  });

  it('falls back for a backslash trick', () => {
    expect(getSafeRedirect('http:\\\\evil.com')).toBe('/app/dashboard');
    expect(getSafeRedirect('/\\evil.com')).toBe('/app/dashboard');
  });

  it('falls back for a percent-encoded protocol-relative URL', () => {
    expect(getSafeRedirect('/%2f%2fevil.com')).toBe('/app/dashboard');
  });

  it('falls back for a javascript: scheme', () => {
    expect(getSafeRedirect('javascript:alert(1)')).toBe('/app/dashboard');
  });

  it('falls back for empty or null input', () => {
    expect(getSafeRedirect(null)).toBe('/app/dashboard');
    expect(getSafeRedirect(undefined)).toBe('/app/dashboard');
    expect(getSafeRedirect('')).toBe('/app/dashboard');
  });

  it('honors a custom fallback', () => {
    expect(getSafeRedirect('https://evil.com', '/app')).toBe('/app');
  });
});
