import { PageIntro } from '@/components/ui/PageIntro';
import { topNavLinks } from '@/data/navigation';
import { ShowcaseShell, ShowcaseSurface } from '@/components/showcase/ShowcaseShell';

const appGroups = [
  {
    label: 'Coach',
    items: ['Dashboard', 'Sessions', 'Compare', 'Visualization', 'Leaderboard'],
  },
  {
    label: 'Strategy',
    items: ['Race Strategy'],
  },
  {
    label: 'Engineer',
    items: ['Tracks', 'Drivers', 'Karts', 'Weekends'],
  },
];

const mobileSections = [
  {
    label: 'Racers',
    items: ['Product', 'Demo', 'Pricing'],
  },
  {
    label: 'Teams',
    items: ['Venue Tools', 'Contact', 'Status'],
  },
];

const sectionTabs = ['Overview', 'Race Control', 'Reports', 'Assets'];

function SectionTabStrip() {
  return (
    <div className="flex flex-wrap gap-3">
      {sectionTabs.map((tab, index) => (
        <button
          key={tab}
          type="button"
          className={`rounded-full border px-4 py-2 font-telemetry text-[11px] uppercase tracking-[0.18em] transition-colors ${
            index === 1
              ? 'border-acid-green/50 bg-acid-green/10 text-acid-green'
              : 'border-white/10 text-steel hover:border-white/20 hover:text-chalk'
          }`}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

function MarketingHeaderStage() {
  return (
    <div className="overflow-hidden rounded-[24px] border border-white/10 bg-[linear-gradient(180deg,rgba(14,14,14,0.96),rgba(7,7,7,0.94))]">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 px-6 py-5">
        <div className="flex items-center gap-6">
          <div>
            <p className="font-monument text-2xl text-chalk">LAP</p>
            <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
              Motorsport Intelligence
            </p>
          </div>
          <nav className="hidden gap-3 lg:flex">
            {topNavLinks.map((link) => (
              <span
                key={link.href}
                className="rounded-full border border-white/10 px-4 py-2 font-body text-sm text-steel"
              >
                {link.label}
              </span>
            ))}
          </nav>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-full border border-acid-green/25 bg-acid-green/10 px-3 py-1 font-telemetry text-[10px] uppercase tracking-[0.18em] text-acid-green">
            Demo Ready
          </span>
          <button
            type="button"
            className="rounded-full border border-white/10 px-4 py-2 font-body text-sm text-chalk"
          >
            Sign In
          </button>
          <button
            type="button"
            className="rounded-full bg-gold px-4 py-2 font-telemetry text-xs uppercase tracking-[0.14em] text-black"
          >
            Book Demo
          </button>
        </div>
      </div>

      <div className="grid gap-8 px-6 py-8 lg:grid-cols-[1.3fr_0.8fr]">
        <div>
          <PageIntro
            eyebrow="Marketing Navigation"
            title="Header, nav logic, and launch CTAs"
            subtitle="Primary routes stay lightweight while demo, pricing, and contact actions remain visible at the first scan."
            badge="Desktop"
          />
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
                Primary Actions
              </p>
              <p className="mt-3 font-monument text-lg text-chalk">Book Demo / Sign In</p>
              <p className="mt-2 font-body text-sm leading-6 text-steel">
                Conversion actions remain visible without hiding product discovery links.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
                Product Discovery
              </p>
              <p className="mt-3 font-monument text-lg text-chalk">Product / Pricing / Demo</p>
              <p className="mt-2 font-body text-sm leading-6 text-steel">
                Balanced top-level IA for users arriving cold from search or sales traffic.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
                Supportive Context
              </p>
              <p className="mt-3 font-monument text-lg text-chalk">Status / Contact / Trust</p>
              <p className="mt-2 font-body text-sm leading-6 text-steel">
                Secondary surfaces point to operational confidence instead of generic footer-only links.
              </p>
            </div>
          </div>
        </div>

        <div className="rounded-[28px] border border-white/10 bg-black/40 p-5">
          <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-acid-green">
            Header Tokens
          </p>
          <div className="mt-4 space-y-4">
            {[
              ['Logo lockup', 'Monument wordmark with telemetry subtitle'],
              ['Nav spacing', 'Comfortable click targets for desktop and tablet breakpoints'],
              ['CTA rhythm', 'One neutral action and one high-contrast conversion action'],
              ['Status signal', 'Demo-ready pill reinforces live product availability'],
            ].map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
                  {label}
                </p>
                <p className="mt-2 font-body text-sm leading-6 text-chalk/90">{value}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function MobileDrawerStage() {
  return (
    <div className="grid gap-6 lg:grid-cols-[0.72fr_1fr]">
      <div className="max-w-sm rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(12,12,12,0.98),rgba(5,5,5,0.98))] p-5 shadow-[0_24px_70px_-36px_rgba(0,0,0,0.8)]">
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div>
            <p className="font-monument text-2xl text-chalk">LAP</p>
            <p className="font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
              Drawer Navigation
            </p>
          </div>
          <span className="rounded-full border border-white/10 px-3 py-1 font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
            Menu
          </span>
        </div>

        <div className="mt-5 space-y-5">
          {mobileSections.map((section) => (
            <div key={section.label}>
              <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-acid-green">
                {section.label}
              </p>
              <div className="mt-3 space-y-2">
                {section.items.map((item, index) => (
                  <div
                    key={item}
                    className={`flex items-center justify-between rounded-2xl border px-4 py-3 ${
                      index === 0 && section.label === 'Racers'
                        ? 'border-acid-green/30 bg-acid-green/10 text-chalk'
                        : 'border-white/10 bg-white/[0.03] text-steel'
                    }`}
                  >
                    <span className="font-body text-sm">{item}</span>
                    <span className="font-telemetry text-[10px] uppercase tracking-[0.16em]">
                      Open
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-6 grid gap-3 border-t border-white/10 pt-4">
          <button
            type="button"
            className="rounded-full border border-white/10 px-4 py-3 font-body text-sm text-chalk"
          >
            Contact Sales
          </button>
          <button
            type="button"
            className="rounded-full bg-gold px-4 py-3 font-telemetry text-xs uppercase tracking-[0.14em] text-black"
          >
            Start Demo
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {[
          ['Audience Grouping', 'Drawer sections separate racer acquisition from venue and team workflows.'],
          ['Tap Targets', 'Large row blocks avoid cramped menu density on small screens.'],
          ['CTA Persistence', 'Commercial actions stay in reach even after users dive into menu exploration.'],
          ['Transition State', 'This drawer is intentionally capture-friendly and mirrors the app overlay rhythm.'],
        ].map(([label, body]) => (
          <div key={label} className="rounded-[24px] border border-white/10 bg-white/[0.03] p-5">
            <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
              {label}
            </p>
            <p className="mt-3 font-monument text-lg text-chalk">{label}</p>
            <p className="mt-3 font-body text-sm leading-6 text-steel">{body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function AppShellStage() {
  return (
    <div className="overflow-hidden rounded-[28px] border border-white/10 bg-[#060606]">
      <div className="grid min-h-[620px] lg:grid-cols-[240px_1fr]">
        <aside className="border-r border-white/10 bg-concrete/90 p-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div>
              <p className="font-monument text-2xl text-chalk">LAP</p>
              <p className="font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
                App Shell
              </p>
            </div>
            <span className="font-telemetry text-xs text-steel">{'<'}</span>
          </div>

          <div className="mt-4 space-y-5">
            {appGroups.map((group) => (
              <div key={group.label}>
                <p className="px-2 font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel/70">
                  {group.label}
                </p>
                <div className="mt-2 space-y-1">
                  {group.items.map((item, index) => (
                    <div
                      key={item}
                      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 ${
                        group.label === 'Strategy' && index === 0
                          ? 'border border-acid-green/30 bg-acid-green/10 text-acid-green'
                          : 'text-steel'
                      }`}
                    >
                      <span className="font-telemetry text-xs text-steel/70">{String(index + 1).padStart(2, '0')}</span>
                      <span className="font-body text-sm">{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
              Utility
            </p>
            <div className="mt-3 space-y-2 text-sm text-chalk/90">
              <p>Help</p>
              <p>Account</p>
              <p className="text-safety-red">Log out</p>
            </div>
          </div>
        </aside>

        <div className="flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 bg-asphalt/95 px-6 py-4">
            <div className="flex items-center gap-3">
              <span className="rounded-full border border-white/10 px-3 py-1 font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
                Ctrl+K
              </span>
              <div className="min-w-[220px] rounded-full border border-white/10 bg-white/[0.02] px-4 py-2 font-body text-sm text-steel">
                Search sessions, drivers, reports...
              </div>
            </div>

            <div className="flex items-center gap-3">
              <span className="rounded-full border border-white/10 px-3 py-2 font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
                Metric
              </span>
              <button
                type="button"
                className="rounded-full bg-gold px-4 py-2 font-telemetry text-xs uppercase tracking-[0.14em] text-black"
              >
                Upload
              </button>
            </div>
          </div>

          <div className="space-y-6 px-6 py-6">
            <div>
              <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-steel">
                Breadcrumb
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2 font-body text-sm text-steel">
                <span>App</span>
                <span>/</span>
                <span>Race Strategy</span>
                <span>/</span>
                <span className="text-chalk">24H Spa Plan</span>
              </div>
            </div>

            <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-5">
              <PageIntro
                eyebrow="Workflow Navigation"
                title="Race Strategy command center"
                subtitle="Sidebar grouping, breadcrumb depth, tabs, and top-bar shortcuts all align around endurance planning."
                badge="In App"
              />
              <SectionTabStrip />

              <div className="mt-6 grid gap-4 md:grid-cols-3">
                {[
                  ['Pinned Context', 'Breadcrumb and intro keep route depth legible during long sessions.'],
                  ['Mode Switches', 'Tabs support movement between strategy, race control, and report modes.'],
                  ['Search and Upload', 'Top bar utilities stay accessible without overwhelming the content frame.'],
                ].map(([label, body]) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-black/30 p-4">
                    <p className="font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
                      {label}
                    </p>
                    <p className="mt-3 font-body text-sm leading-6 text-chalk/90">{body}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[24px] border border-white/10 bg-black/30 p-5">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-4">
                <div>
                  <p className="font-telemetry text-[10px] uppercase tracking-[0.18em] text-acid-green">
                    Command Palette
                  </p>
                  <p className="mt-2 font-monument text-lg text-chalk">Cross-surface navigation and actions</p>
                </div>
                <span className="rounded-full border border-acid-green/20 bg-acid-green/10 px-3 py-1 font-telemetry text-[10px] uppercase tracking-[0.16em] text-acid-green">
                  Keyboard First
                </span>
              </div>

              <div className="mt-5 rounded-[24px] border border-white/10 bg-[#070707] p-4">
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 font-body text-sm text-steel">
                  Search commands, routes, and recent sessions
                </div>
                <div className="mt-4 space-y-2">
                  {[
                    ['Go to Race Strategy', 'Jump to live pit wall or builder'],
                    ['Open Weekend Report', 'Recent report for Round 3 - Spa'],
                    ['Start Upload', 'Fast path to ingest new session data'],
                    ['Compare Drivers', 'Open benchmark workflow'],
                  ].map(([label, body], index) => (
                    <div
                      key={label}
                      className={`flex items-center justify-between rounded-2xl border px-4 py-3 ${
                        index === 0
                          ? 'border-acid-green/30 bg-acid-green/10'
                          : 'border-white/10 bg-white/[0.02]'
                      }`}
                    >
                      <div>
                        <p className="font-body text-sm text-chalk">{label}</p>
                        <p className="mt-1 font-body text-xs text-steel">{body}</p>
                      </div>
                      <span className="font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
                        Enter
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function NavigationShowcasePage() {
  return (
    <ShowcaseShell
      eyebrow="Navigation Showcase"
      title="Headers, drawers, shells, and navigation utilities"
      description="Dedicated capture surface for the foundational navigation language across marketing, mobile, and authenticated app flows."
      links={[
        { href: '/gamification-showcase', label: 'Gamification' },
        { href: '/strategy-showcase', label: 'Race Strategy' },
        { href: '/reports-showcase', label: 'Reports' },
      ]}
    >
      <ShowcaseSurface
        eyebrow="Marketing"
        title="Landing header and conversion framing"
      >
        <MarketingHeaderStage />
      </ShowcaseSurface>

      <ShowcaseSurface
        eyebrow="Mobile"
        title="Drawer structure and small-screen actions"
      >
        <MobileDrawerStage />
      </ShowcaseSurface>

      <ShowcaseSurface
        eyebrow="Application"
        title="Sidebar, breadcrumb, tabs, and command palette"
      >
        <AppShellStage />
      </ShowcaseSurface>
    </ShowcaseShell>
  );
}
