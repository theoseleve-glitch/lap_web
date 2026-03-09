import { JsonLd } from '@/components/seo/JsonLd';
import { PageIntro } from '@/components/ui/PageIntro';
import { generateSeoMetadata } from '@/lib/seo';

export const metadata = generateSeoMetadata('/accessibility');

export default function AccessibilityPage() {
  return (
    <>
    <JsonLd pathname="/accessibility" />
    <main className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <PageIntro
        title="Accessibility Statement"
        subtitle="LAP is committed to making motorsport telemetry analysis accessible to everyone."
      />

      <div className="space-y-8 text-sm text-steel leading-relaxed">
        <section>
          <h2 className="text-lg font-semibold text-chalk mb-2">Our Commitment</h2>
          <p>
            We strive to ensure that the LAP platform conforms to the{' '}
            <a
              href="https://www.w3.org/TR/WCAG22/"
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="text-lap-green hover:underline"
            >
              Web Content Accessibility Guidelines (WCAG) 2.2
            </a>{' '}
            at Level AA. This applies to our marketing site and the authenticated
            application dashboard.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-chalk mb-2">Measures Taken</h2>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>Semantic HTML with proper heading hierarchy throughout</li>
            <li>ARIA labels on all chart containers and interactive elements</li>
            <li>Keyboard navigation support including skip-to-content link</li>
            <li>Visible focus indicators using <code className="text-chalk bg-concrete px-1 rounded">:focus-visible</code> outlines</li>
            <li>Minimum 44px tap targets on interactive elements for mobile users</li>
            <li>Colour contrast ratios meeting WCAG AA standards for primary text</li>
            <li>Command palette (Ctrl+K / Cmd+K) for fast keyboard-driven navigation</li>
            <li>Breadcrumb navigation with <code className="text-chalk bg-concrete px-1 rounded">aria-current</code> marking</li>
            <li>Responsive design tested across screen sizes from 320px to 2560px</li>
            <li>Reduced motion support via <code className="text-chalk bg-concrete px-1 rounded">prefers-reduced-motion</code></li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-chalk mb-2">Known Limitations</h2>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>Interactive chart visualisations (speed trace, GPS map, G-G diagram) rely on canvas elements that are not fully screen-reader accessible. We provide aria-label descriptions and tabular data alternatives where possible.</li>
            <li>Some decorative text uses reduced opacity that may not meet AAA contrast ratios.</li>
            <li>Third-party embedded content (Stripe checkout, OAuth flows) follows the accessibility standards of those providers.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-chalk mb-2">Assistive Technologies</h2>
          <p>The platform has been tested with:</p>
          <ul className="list-disc list-inside space-y-1 ml-2 mt-2">
            <li>VoiceOver (macOS / iOS)</li>
            <li>Keyboard-only navigation (Chrome, Firefox, Safari)</li>
            <li>Browser zoom up to 200%</li>
          </ul>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-chalk mb-2">Feedback</h2>
          <p>
            If you encounter an accessibility barrier or have suggestions for improvement,
            please contact us at{' '}
            <a
              href="mailto:accessibility@lap-coach.racing"
              className="text-lap-green hover:underline"
            >
              accessibility@lap-coach.racing
            </a>
            . We aim to respond within 5 business days.
          </p>
        </section>

        <p className="text-xs text-steel/60 pt-4 border-t border-steel/20">
          This statement was last updated on 2026-03-09.
        </p>
      </div>
    </main>
    </>
  );
}
