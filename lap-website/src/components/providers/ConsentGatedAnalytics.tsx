'use client';

import { useEffect, useState } from 'react';
import Script from 'next/script';
import { hasAnalyticsConsent, CONSENT_CHANGED_EVENT } from '@/lib/consent';

interface Props {
  dataDomain: string;
}

/**
 * Conditionally injects the Plausible analytics script only when
 * the user has granted analytics consent. Listens for consent
 * changes so the script loads immediately after acceptance.
 */
export function ConsentGatedAnalytics({ dataDomain }: Props) {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    setAllowed(hasAnalyticsConsent());

    const onConsentChange = () => setAllowed(hasAnalyticsConsent());
    window.addEventListener(CONSENT_CHANGED_EVENT, onConsentChange);
    return () => window.removeEventListener(CONSENT_CHANGED_EVENT, onConsentChange);
  }, []);

  if (!allowed) return null;

  return (
    <Script
      defer
      data-domain={dataDomain}
      src="https://plausible.io/js/script.js"
      strategy="afterInteractive"
    />
  );
}
