'use client';

import { forwardRef, useCallback, useEffect, useId, useImperativeHandle, useRef } from 'react';
import Script from 'next/script';

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        options: {
          sitekey: string;
          callback: (token: string) => void;
          'error-callback'?: () => void;
          'expired-callback'?: () => void;
        },
      ) => string;
      remove: (widgetId: string) => void;
      reset: (widgetId: string) => void;
    };
  }
}

interface TurnstileWidgetProps {
  sitekey: string;
  onToken: (token: string) => void;
}

/** Imperative handle so a parent (e.g. the login page) can force the
 * widget to reset after a rejected resubmit -- see login/page.tsx's
 * handleTurnstileToken, which resets on a still-failing retry so the user
 * always has a live widget to retry with (never a dead end). */
export interface TurnstileWidgetHandle {
  reset: () => void;
}

/**
 * Renders the Cloudflare Turnstile step-up challenge widget.
 *
 * Only ever mounted after the backend responds to /auth/login with a 428
 * challenge_required (see useAuth().login / lib/auth.ts) -- if Turnstile is
 * never configured server-side, the backend never returns 428, so this
 * component never renders. See auth/turnstile.py + auth/lockout.py
 * (challenge_required) on the backend for the full contract.
 *
 * Turnstile tokens are single-use and expire after ~300s: `error-callback`
 * and `expired-callback` reset the widget in place so an errored or
 * expired token never leaves a stale/blank widget behind.
 */
export const TurnstileWidget = forwardRef<TurnstileWidgetHandle, TurnstileWidgetProps>(
  function TurnstileWidget({ sitekey, onToken }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const widgetIdRef = useRef<string | null>(null);
    const domId = useId();

    const reset = useCallback(() => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.reset(widgetIdRef.current);
      }
    }, []);

    useImperativeHandle(ref, () => ({ reset }), [reset]);

    // Handles the case where the script is already loaded (e.g. a second
    // mount after the widget was dismissed and re-shown) -- Script's onLoad
    // only fires once per page load, not per mount.
    const renderWidget = useCallback(() => {
      if (widgetIdRef.current || !window.turnstile || !containerRef.current) return;
      widgetIdRef.current = window.turnstile.render(containerRef.current, {
        sitekey,
        callback: onToken,
        // A widget error or an expired token must never leave a dead/blank
        // widget -- reset it in place so the user gets a fresh challenge.
        'error-callback': reset,
        'expired-callback': reset,
      });
    }, [sitekey, onToken, reset]);

    useEffect(() => {
      renderWidget();
      return () => {
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.remove(widgetIdRef.current);
          widgetIdRef.current = null;
        }
      };
    }, [renderWidget]);

    return (
      <>
        <Script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js"
          strategy="afterInteractive"
          onLoad={renderWidget}
        />
        <div ref={containerRef} id={`turnstile-${domId}`} className="my-4 flex justify-center" />
      </>
    );
  },
);
