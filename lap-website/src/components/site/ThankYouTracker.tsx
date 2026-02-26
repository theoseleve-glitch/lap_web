'use client';

import { useEffect } from 'react';
import { trackFormSubmitSuccess } from '@/lib/analytics';

interface ThankYouTrackerProps {
  formType: string;
}

export function ThankYouTracker({ formType }: ThankYouTrackerProps) {
  useEffect(() => {
    void trackFormSubmitSuccess(formType, `/thank-you/${formType}`);
  }, [formType]);

  return null;
}
