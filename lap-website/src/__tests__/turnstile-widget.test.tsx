/**
 * Unit tests for TurnstileWidget's reset behavior (Fix #2a/#2b in the
 * Turnstile step-up hardening pass): Cloudflare Turnstile tokens are
 * single-use and expire after ~300s, so an errored or expired token must
 * never leave a stale/blank widget -- and a parent (the login page, on a
 * rejected resubmit) must be able to force a reset too. See
 * src/components/auth/TurnstileWidget.tsx and
 * src/app/(auth)/login/page.tsx::handleTurnstileToken.
 *
 * next/script is stubbed to a no-op so the widget's own useEffect (which
 * already handles the "script already loaded" case) is what drives
 * window.turnstile.render -- mirroring how the real component behaves once
 * the third-party script has loaded.
 */
import { createRef } from 'react';
import { render } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('next/script', () => ({
  default: () => null,
}));

import { TurnstileWidget, type TurnstileWidgetHandle } from '@/components/auth/TurnstileWidget';

describe('TurnstileWidget', () => {
  let renderMock: ReturnType<typeof vi.fn>;
  let resetMock: ReturnType<typeof vi.fn>;
  let removeMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    renderMock = vi.fn(() => 'widget-id-1');
    resetMock = vi.fn();
    removeMock = vi.fn();
    window.turnstile = { render: renderMock, remove: removeMock, reset: resetMock };
  });

  function renderedOptions() {
    expect(renderMock).toHaveBeenCalledTimes(1);
    return renderMock.mock.calls[0][1];
  }

  it('forwards a completed token via callback (success path unchanged)', () => {
    const onToken = vi.fn();
    render(<TurnstileWidget sitekey="test-sitekey" onToken={onToken} />);

    renderedOptions().callback('a-real-token');

    expect(onToken).toHaveBeenCalledWith('a-real-token');
  });

  it('resets the widget when Turnstile fires error-callback', () => {
    render(<TurnstileWidget sitekey="test-sitekey" onToken={vi.fn()} />);

    renderedOptions()['error-callback']();

    expect(resetMock).toHaveBeenCalledWith('widget-id-1');
  });

  it('resets the widget when Turnstile fires expired-callback', () => {
    render(<TurnstileWidget sitekey="test-sitekey" onToken={vi.fn()} />);

    renderedOptions()['expired-callback']();

    expect(resetMock).toHaveBeenCalledWith('widget-id-1');
  });

  it('exposes reset() via ref so a parent can force a reset (e.g. a rejected resubmit)', () => {
    const ref = createRef<TurnstileWidgetHandle>();
    render(<TurnstileWidget ref={ref} sitekey="test-sitekey" onToken={vi.fn()} />);
    renderedOptions();

    ref.current?.reset();

    expect(resetMock).toHaveBeenCalledWith('widget-id-1');
  });
});
