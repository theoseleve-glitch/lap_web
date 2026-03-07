/**
 * Marketing page template component.
 *
 * Enforces section order: Hero -> Proof -> HowItWorks -> Features -> CTA -> FAQ
 * Required sections: Hero, CTA. Others are optional but must be in order.
 *
 * Usage:
 *   <MarketingPageTemplate
 *     hero={<HeroSection ... />}
 *     proof={<ProofSection ... />}
 *     howItWorks={<HowItWorks ... />}
 *     features={<FeatureGrid ... />}
 *     cta={<CtaSection ... />}
 *     faq={<FaqSection ... />}
 *   />
 */

import { type ReactNode } from 'react';

interface MarketingPageTemplateProps {
  hero: ReactNode;
  proof?: ReactNode;
  howItWorks?: ReactNode;
  features?: ReactNode;
  cta: ReactNode;
  faq?: ReactNode;
}

export function MarketingPageTemplate({
  hero,
  proof,
  howItWorks,
  features,
  cta,
  faq,
}: MarketingPageTemplateProps) {
  return (
    <>
      {/* hero */}
      {hero}
      {/* proof */}
      {proof}
      {/* how-it-works */}
      {howItWorks}
      {/* features */}
      {features}
      {/* cta */}
      {cta}
      {/* faq */}
      {faq}
    </>
  );
}
