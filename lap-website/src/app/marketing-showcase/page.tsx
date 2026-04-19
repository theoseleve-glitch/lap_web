import type { ReactNode } from 'react';
import { ShowcaseShell, ShowcaseSurface } from '@/components/showcase/ShowcaseShell';
import { PageIntro } from '@/components/ui/PageIntro';

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-steel/20 bg-concrete/40 p-4">
      <h3 className="font-telemetry text-xs uppercase tracking-wider text-steel">{title}</h3>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function Field({ label, value, error }: { label: string; value: string; error?: string }) {
  return (
    <div>
      <p className="mb-1 font-telemetry text-[11px] uppercase tracking-[0.08em] text-steel">{label}</p>
      <div className={`rounded border px-3 py-2 text-sm ${error ? 'border-safety-red/40 bg-safety-red/5 text-chalk' : 'border-steel/30 bg-asphalt text-chalk'}`}>
        {value}
      </div>
      {error ? <p className="mt-1 text-xs text-safety-red">{error}</p> : null}
    </div>
  );
}

function Chip({ label, tone = 'default' }: { label: string; tone?: 'default' | 'green' | 'gold' }) {
  const className =
    tone === 'green'
      ? 'border-acid-green/30 bg-acid-green/10 text-acid-green'
      : tone === 'gold'
        ? 'border-gold/30 bg-gold/10 text-gold'
        : 'border-steel/30 bg-steel/10 text-steel';
  return (
    <span className={`inline-flex rounded border px-2 py-0.5 font-telemetry text-[10px] uppercase tracking-[0.12em] ${className}`}>
      {label}
    </span>
  );
}

function MarketingChromeStage() {
  return (
    <div className="space-y-6">
      <div className="rounded-[24px] border border-white/10 bg-asphalt/95 p-4 backdrop-blur">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full border border-chalk/20 text-chalk">L</div>
            <span className="font-monument text-xl text-chalk">LAP</span>
          </div>
          <div className="hidden gap-2 md:flex">
            {['Product', 'Pricing', 'Demo', 'Contact', 'Login'].map((item, index) => (
              <span key={item} className={`inline-flex min-h-[44px] items-center border px-3 py-2 font-telemetry text-xs uppercase tracking-[0.12em] ${index === 1 ? 'border-pit-orange text-chalk' : 'border-chalk/20 text-steel'}`}>
                {item}
              </span>
            ))}
            <span className="inline-flex min-h-[44px] items-center border border-pit-orange bg-pit-orange px-3 py-2 font-telemetry text-xs uppercase tracking-[0.12em] text-white">Sign Up</span>
          </div>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
        <Card title="Sticky Section Tabs + Cookie Consent">
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Chip label="Overview" tone="green" />
              <Chip label="Features" />
              <Chip label="FAQ" />
              <Chip label="CTA" />
            </div>
            <div className="rounded-lg border border-chalk/15 bg-black/50 p-4 text-sm text-steel">
              First-visit cookie overlay anchored above the footer with accept and privacy actions.
            </div>
          </div>
        </Card>
        <Card title="Footer Pattern">
          <div className="grid gap-4 md:grid-cols-3">
            <div><p className="mb-2 font-telemetry text-[10px] uppercase tracking-[0.12em] text-steel">Links</p><p className="text-sm text-chalk">Contact, Demo, Help, Security</p></div>
            <div><p className="mb-2 font-telemetry text-[10px] uppercase tracking-[0.12em] text-steel">Social</p><p className="text-sm text-chalk">Instagram, YouTube, LinkedIn</p></div>
            <div><p className="mb-2 font-telemetry text-[10px] uppercase tracking-[0.12em] text-steel">Trust</p><p className="text-sm text-chalk">GDPR Ready, EU Residency, TLS + AES-256</p></div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function HomeHeroStage() {
  return (
    <div className="space-y-6">
      <Card title="Start Grid Hero">
        <div className="rounded-[28px] border border-gold/20 bg-[radial-gradient(circle_at_top,rgba(212,179,90,0.18),transparent_35%),linear-gradient(180deg,#0a0a0a,#050505)] p-8">
          <p className="font-telemetry text-xs uppercase tracking-[0.18em] text-gold">Find Time</p>
          <h2 className="mt-4 max-w-3xl font-monument text-4xl leading-tight text-chalk">
            Start-lights landing sequence for telemetry coaching and race-day decision support.
          </h2>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-steel">
            The homepage opens like a race start, then drops into pain points, live telemetry sculpture,
            and a guided product narrative.
          </p>
          <div className="mt-6 flex gap-3">
            <span className="rounded border border-pit-orange bg-pit-orange px-4 py-2 font-telemetry text-xs uppercase tracking-[0.12em] text-white">Start Free Report</span>
            <span className="rounded border border-chalk/20 px-4 py-2 font-telemetry text-xs uppercase tracking-[0.12em] text-steel">See Demo</span>
          </div>
        </div>
      </Card>
      <div className="grid gap-4 md:grid-cols-4">
        {['Light 1', 'Light 2', 'Light 3', 'Light 4'].map((light, index) => (
          <div key={light} className={`h-16 rounded-full border ${index === 3 ? 'border-pit-orange bg-pit-orange/20' : 'border-chalk/15 bg-black/40'}`} />
        ))}
      </div>
    </div>
  );
}

function HomeNarrativeStage() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card title="Pain + Time Loss">
          <div className="space-y-3">
            <p className="text-sm text-steel">Interactive pain section with live delta callouts and corner-loss framing.</p>
            <div className="h-44 rounded bg-asphalt" />
          </div>
        </Card>
        <Card title="Telemetry Sculpture">
          <div className="h-56 rounded bg-[radial-gradient(circle_at_40%_30%,rgba(0,212,255,0.18),transparent_35%),linear-gradient(180deg,#101010,#050505)]" />
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Pipeline">
          <div className="grid gap-3 md:grid-cols-4">
            {['Upload', 'Score', 'Fix', 'Improve'].map((step) => (
              <div key={step} className="rounded border border-steel/20 bg-asphalt px-3 py-4 text-center font-telemetry text-xs uppercase tracking-[0.12em] text-chalk">{step}</div>
            ))}
          </div>
        </Card>
        <Card title="Timing vs Coaching">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded border border-safety-red/20 bg-safety-red/5 p-4 text-sm text-steel">Timing-only stack</div>
            <div className="rounded border border-acid-green/20 bg-acid-green/5 p-4 text-sm text-steel">Telemetry + coaching stack</div>
          </div>
        </Card>
        <Card title="Marquee Strip">
          <p className="text-sm text-steel">TELEMETRY / CORNER COACHING / EXECUTION / ROBUSTNESS / TRACK MAPPING</p>
        </Card>
      </div>
    </div>
  );
}

function HomeConversionStage() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <Card title="Product Tabs + Workflow Coverage">
          <div className="flex flex-wrap gap-2">
            <Chip label="Reports" tone="green" />
            <Chip label="Visualization" />
            <Chip label="Race Strategy" />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="h-48 rounded bg-asphalt" />
            <div className="space-y-3">
              <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Upload and Analyze</div>
              <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Compare and Visualize</div>
              <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Plan and Execute</div>
            </div>
          </div>
        </Card>
        <Card title="Pit Stop + Garage + Podium">
          <div className="space-y-3">
            <div className="rounded border border-gold/20 bg-gold/5 p-4 text-sm text-steel">Pricing, FAQ, and trust block</div>
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Technical accordion with security and format support</div>
            <div className="rounded border border-pit-orange/20 bg-pit-orange/5 p-4 text-sm text-steel">Final CTA with restart link</div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function ProductStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Product" subtitle="Workflow coverage, coaching galleries, race-day tool galleries, and related content." />
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card title="Workflow Coverage">
          <div className="space-y-3">
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Upload and analyze telemetry</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Review reports and focus-mode drilldowns</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Plan race-day strategy and pit timing</div>
          </div>
        </Card>
        <Card title="Coaching Gallery">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="h-40 rounded bg-asphalt" />
            <div className="h-40 rounded bg-asphalt" />
            <div className="h-40 rounded border border-acid-green/30 bg-acid-green/5" />
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Race Day Tools Gallery">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="h-40 rounded bg-asphalt" />
            <div className="h-40 rounded bg-asphalt" />
            <div className="h-40 rounded bg-asphalt" />
          </div>
        </Card>
        <Card title="Next Actions">
          <div className="flex gap-3">
            <span className="rounded border border-pit-orange px-4 py-2 font-telemetry text-xs uppercase tracking-[0.12em] text-gold">Start Free Report</span>
            <span className="rounded border border-steel/30 px-4 py-2 font-telemetry text-xs uppercase tracking-[0.12em] text-chalk">Compare Plans</span>
          </div>
        </Card>
        <Card title="Share + Related">
          <p className="text-sm text-steel">Social share row plus related pages cards close the page.</p>
        </Card>
      </div>
    </div>
  );
}

function PricingStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Pricing" subtitle="Annual billing state with pricing cards, feature matrix, and trust layers." />
      <div className="flex items-center justify-center gap-3">
        <span className="font-telemetry text-[11px] text-steel">Monthly</span>
        <div className="relative h-6 w-12 border border-steel/30 bg-concrete"><div className="absolute top-1 left-[calc(100%-20px)] h-4 w-4 bg-pit-orange" /></div>
        <span className="font-telemetry text-[11px] text-chalk">Annual</span>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        {['Demo', 'Racer', 'World Class'].map((plan, index) => (
          <Card key={plan} title={plan}>
            <div className={`rounded-lg border p-4 ${index === 1 ? 'border-pit-orange bg-pit-orange/5' : 'border-steel/20 bg-asphalt'}`}>
              <p className="font-monument text-2xl text-chalk">{index === 0 ? '0' : index === 1 ? '29' : '99'} EUR</p>
              <p className="mt-2 text-sm text-steel">Plan CTA, entitlement bullets, and feature chips.</p>
            </div>
          </Card>
        ))}
      </div>
      <Card title="Feature Matrix">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Upload and Analyze</div>
          <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Race Strategy Dashboard</div>
          <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Visualization Workspace</div>
          <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Retention</div>
        </div>
      </Card>
    </div>
  );
}

function PricingExpandedStage() {
  return (
    <div className="space-y-6">
      <Card title="Expanded Matrix + FAQ Open">
        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-3">
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Comparison Progress / Coaching Drills / Optimizer Modes</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Live Pace / Pit Planning / API Access</div>
          </div>
          <div className="space-y-3">
            <div className="rounded border border-gold/20 bg-gold/5 p-4 text-sm text-steel">FAQ accordion with one answer open</div>
            <div className="rounded border border-acid-green/20 bg-acid-green/5 p-4 text-sm text-steel">Sticky mobile CTA bar + checkout confirmation modal</div>
          </div>
        </div>
      </Card>
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Data Lifecycle"><div className="h-32 rounded bg-asphalt" /></Card>
        <Card title="Trust Strip"><div className="h-32 rounded bg-asphalt" /></Card>
        <Card title="Related Pages"><div className="h-32 rounded bg-asphalt" /></Card>
      </div>
    </div>
  );
}

function DemoStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Demo" subtitle="Reversible intro card, auth-sensitive CTA state, and lightweight coverage checklist." />
      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <Card title="Reversible Card">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded border border-acid-green/20 bg-acid-green/5 p-4 text-sm text-steel">Front face: B2C value pitch</div>
            <div className="rounded border border-gold/20 bg-gold/5 p-4 text-sm text-steel">Back face: alternate angle / flipped state</div>
          </div>
        </Card>
        <Card title="CTA States">
          <div className="space-y-3">
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Logged out: Create Free Account</div>
            <div className="rounded border border-acid-green/20 bg-acid-green/5 p-4 text-sm text-steel">Logged in: Go to Analysis + Dashboard</div>
          </div>
        </Card>
      </div>
      <Card title="Coverage Checklist">
        <ol className="space-y-2 text-sm text-steel">
          <li>Upload a session and receive a full coaching report.</li>
          <li>Inspect corner-level losses and comparison workflows.</li>
          <li>Move into the dashboard or analysis workspace directly.</li>
        </ol>
      </Card>
    </div>
  );
}

function ContactStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Contact" subtitle="Lead form with validation state and service expectations." />
      <div className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
        <Card title="Contact Form">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Name" value="Alex Mercier" />
            <Field label="Email" value="alex@" error="Enter a valid email address." />
            <Field label="Company" value="Apex Karting" />
            <Field label="Phone" value="+33 6 11 22 33 44" />
            <div className="md:col-span-2">
              <Field label="Message" value="We want to evaluate LAP for post-session driver coaching." />
            </div>
          </div>
          <div className="mt-4 rounded border border-safety-red/25 bg-safety-red/5 px-3 py-3 text-sm text-steel">Submission error state sits above the CTA when the API rejects the request.</div>
        </Card>
        <Card title="Response Expectations">
          <ul className="space-y-2 text-sm text-steel">
            <li>Response within one business day.</li>
            <li>Product, sales, and support routing guidance.</li>
            <li>Expectation-setting on pilots and onboarding.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

function BookStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Book a Call" subtitle="Booking flow with plan, team size, preferred date, and discovery-call coverage." />
      <div className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
        <Card title="Booking Form">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Name" value="Sophie Laurent" />
            <Field label="Email" value="sophie@team.example" />
            <Field label="Company" value="Nordic Junior Formula" />
            <Field label="Phone" value="+46 70 000 0000" />
            <Field label="Plan" value="World Class" />
            <Field label="Team Size" value="12 seats" />
            <Field label="Preferred Date" value="2025-10-02" />
            <Field label="Challenge" value="Improve review speed across the coaching team." />
          </div>
        </Card>
        <Card title="What the Call Covers">
          <ul className="space-y-2 text-sm text-steel">
            <li>Telemetry workflow audit.</li>
            <li>Race-day coordination fit.</li>
            <li>Rollout plan and onboarding steps.</li>
            <li>Pricing and team configuration.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

function CustomersStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Customers" subtitle="Editorial case-study page with metric highlights, testimonials, and methodology." />
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card title="Case Studies">
          <div className="space-y-3">
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Kart Racing Academy . 18% faster onboarding</div>
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Junior Single-Seater Team . 11% lower lap-time spread</div>
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Endurance Operation . 2 fewer unplanned pit stops</div>
          </div>
        </Card>
        <Card title="Testimonials">
          <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-1">
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Head Coach quote</div>
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Race Engineer quote</div>
            <div className="rounded border border-steel/20 bg-asphalt p-4 text-sm text-steel">Team Principal quote</div>
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <Card title="Benchmark Methodology">
          <div className="space-y-2 text-sm text-steel">
            <p>Baseline vs intervention periods, normalized track layouts, and published assumptions.</p>
            <p>Editorial/case-study tone instead of direct conversion layout.</p>
          </div>
        </Card>
        <Card title="Bottom CTA + Related">
          <p className="text-sm text-steel">See It In Action CTA, social share row, and related pages close the route.</p>
        </Card>
      </div>
    </div>
  );
}

function VenuesStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="For Venues & Teams" subtitle="B2B landing with feature grid, rollout steps, and pilot-request form." />
      <div className="grid gap-4 md:grid-cols-2">
        {['Hardware + Software', 'Autonomous Reports', 'Branded Experience', 'Zero Staff Pain'].map((item) => (
          <Card key={item} title={item}>
            <p className="text-sm text-steel">Venue-focused value proposition card in the active route style.</p>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <Card title="How It Works">
          <div className="grid gap-3 md:grid-cols-3">
            {['01 Discovery', '02 Pilot Event', '03 Rollout'].map((step) => (
              <div key={step} className="rounded border border-chalk/15 bg-asphalt p-4 text-sm text-chalk">{step}</div>
            ))}
          </div>
        </Card>
        <Card title="Pilot Request Form">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Name" value="Marco Vega" />
            <Field label="Email" value="ops@circuit.example" />
            <Field label="Company" value="Apex Indoor Circuit" />
            <Field label="Plan" value="Venue Pilot" />
          </div>
        </Card>
      </div>
    </div>
  );
}

function InsightsListStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Insights" subtitle="Editorial list page with search, tags, and article cards." />
      <div className="flex gap-3">
        <div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Search insights...</div>
        <div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">All tags</div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Chip label="Telemetry" tone="green" />
        <Chip label="Comparison" />
        <Chip label="Race Strategy" />
        <Chip label="Coaching" />
      </div>
      <div className="space-y-4">
        {['Telemetry Corner Analysis', 'Session vs Session Comparison', 'Race Strategy Dashboard'].map((title) => (
          <Card key={title} title={title}>
            <div className="flex items-center justify-between gap-4">
              <p className="text-sm text-steel">Summary, tag chips, and dual CTA pattern for editorial discovery.</p>
              <div className="flex gap-2"><Chip label="Open Insight" tone="green" /><Chip label="Related Product" /></div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function InsightDetailStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Telemetry Corner Analysis" subtitle="Shared article-detail pattern with content card, tags, and related feature CTA." />
      <div className="flex flex-wrap gap-2">
        <Chip label="Telemetry" tone="green" />
        <Chip label="Corner Coaching" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card title="Article Body">
          <div className="space-y-3 text-sm text-steel">
            <p>Long-form editorial content card with headings, callouts, and product references.</p>
            <div className="h-52 rounded bg-asphalt" />
          </div>
        </Card>
        <Card title="Actions">
          <div className="space-y-3 text-sm text-steel">
            <div className="rounded border border-pit-orange/20 bg-pit-orange/5 p-4">Related feature CTA</div>
            <div className="rounded border border-steel/20 bg-asphalt p-4">Back to insights link</div>
            <div className="rounded border border-steel/20 bg-asphalt p-4">Social share row</div>
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function MarketingShowcasePage() {
  return (
    <ShowcaseShell
      eyebrow="Marketing Website"
      title="Public-site capture surface"
      description="Detailed public marketing capture page covering the homepage narrative, product and pricing flows, demo and lead capture pages, editorial surfaces, and shared chrome."
      links={[
        { href: '/core-sections-showcase', label: 'App Core' },
        { href: '/coach-sections-showcase', label: 'App Coach' },
        { href: '/strategy-showcase', label: 'Strategy' },
      ]}
    >
      <ShowcaseSurface eyebrow="Marketing Chrome" title="Header, sticky tabs, footer, and consent">
        <div id="marketing-showcase-chrome"><MarketingChromeStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Homepage" title="Start Grid hero">
        <div id="marketing-showcase-home-hero"><HomeHeroStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Homepage" title="Narrative middle">
        <div id="marketing-showcase-home-narrative"><HomeNarrativeStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Homepage" title="Conversion close">
        <div id="marketing-showcase-home-conversion"><HomeConversionStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Product" title="Workflow and galleries">
        <div id="marketing-showcase-product"><ProductStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Pricing" title="Default pricing state">
        <div id="marketing-showcase-pricing"><PricingStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Pricing" title="Expanded matrix and CTA states">
        <div id="marketing-showcase-pricing-expanded"><PricingExpandedStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Demo" title="Reversible card and CTA states">
        <div id="marketing-showcase-demo"><DemoStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Contact" title="Lead form">
        <div id="marketing-showcase-contact"><ContactStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Book" title="Booking form">
        <div id="marketing-showcase-book"><BookStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Customers" title="Case studies and testimonials">
        <div id="marketing-showcase-customers"><CustomersStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Venues" title="B2B landing">
        <div id="marketing-showcase-venues"><VenuesStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Insights" title="List page">
        <div id="marketing-showcase-insights-list"><InsightsListStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Insight Detail" title="Article template">
        <div id="marketing-showcase-insight-detail"><InsightDetailStage /></div>
      </ShowcaseSurface>
    </ShowcaseShell>
  );
}
