'use client';

import { useEffect, useId, useRef } from 'react';
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
        },
      ) => string;
      remove: (widgetId: string) => void;
    };
  }
}

interface TurnstileWidgetProps {
  sitekey: string;
  onToken: (token: string) => void;
}

/**
 * Renders the Cloudflare Turnstile step-up challenge widget.
 *
 * Only ever mounted after the backend responds to /auth/login with a 428
 * challenge_required (see useAuth().login / lib/auth.ts) -- if Turnstile is
 * never configured server-side, the backend never returns 428, so this
 * component never renders. See auth/turnstile.py + auth/lockout.py
 * (challenge_required) on the backend for the full contract.
 */
export function TurnstileWidget({ sitekey, onToken }: TurnstileWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  const domId = useId();

  // Handles the case where the script is already loaded (e.g. a second
  // mount after the widget was dismissed and re-shown) -- Script's onLoad
  // only fires once per page load, not per mount.
  useEffect(() => {
    if (widgetIdRef.current || !window.turnstile || !containerRef.current) return;
    widgetIdRef.current = window.turnstile.render(containerRef.current, {
      sitekey,
      callback: onToken,
    });
    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [sitekey, onToken]);

  return (
    <>
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js"
        strategy="afterInteractive"
        onLoad={() => {
          if (!widgetIdRef.current && window.turnstile && containerRef.current) {
            widgetIdRef.current = window.turnstile.render(containerRef.current, {
              sitekey,
              callback: onToken,
            });
          }
        }}
      />
      <div ref={containerRef} id={`turnstile-${domId}`} className="my-4 flex justify-center" />
    </>
  );
}
