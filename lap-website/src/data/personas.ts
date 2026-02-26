export interface PersonaPage {
  slug: 'drivers' | 'circuits' | 'teams' | 'endurance';
  title: string;
  subtitle: string;
  summary: string;
  bullets: string[];
  primaryCta: { label: string; href: string };
  secondaryCta: { label: string; href: string };
}

export const personaPages: PersonaPage[] = [
  {
    slug: 'drivers',
    title: 'For Drivers',
    subtitle: 'Find the next second with every session.',
    summary:
      'Upload telemetry, inspect corners, compare sessions, and turn each debrief into concrete drills for the next run.',
    bullets: [
      'Upload and analyze wizard with metadata and corner confirmation.',
      'Session intelligence tabs for overview, corners, timeline, analytics, and lap data.',
      'Comparison workflows to measure progress against your own best sessions.',
    ],
    primaryCta: { label: 'Book a Demo', href: '/demo?persona=drivers' },
    secondaryCta: { label: 'See Pricing', href: '/pricing?persona=drivers' },
  },
  {
    slug: 'circuits',
    title: 'For Circuits',
    subtitle: 'Give every driver a data-backed debrief at scale.',
    summary:
      'Run high-volume telemetry workflows for events, coaching days, and retention programs without adding hardware friction.',
    bullets: [
      'Race Strategy Control Room for live operational views.',
      'Track, kart, and weekend data management workflows.',
      'Enterprise support options with onboarding and SLA tiers.',
    ],
    primaryCta: { label: 'Book Operator Demo', href: '/book?persona=circuits' },
    secondaryCta: { label: 'Contact Sales', href: '/contact?persona=circuits' },
  },
  {
    slug: 'teams',
    title: 'For Teams',
    subtitle: 'Coordinate drivers, engineers, and analysis in one workspace.',
    summary:
      'Use team workspaces, comparison tools, and coaching plans to move from raw logs to shared race decisions.',
    bullets: [
      'Role-based access controls and workspace scoping.',
      'Driver-vs-driver and session-vs-session comparison modules.',
      'Coaching plans linked to specific corners, drills, and progress checkpoints.',
    ],
    primaryCta: { label: 'Request Team Setup', href: '/contact?persona=teams' },
    secondaryCta: { label: 'View Enterprise Pricing', href: '/pricing?persona=teams' },
  },
  {
    slug: 'endurance',
    title: 'For Endurance Programs',
    subtitle: 'Make long stints measurable and strategic.',
    summary:
      'Track stint trends, fuel windows, driver consistency, and race strategy decisions with live and post-session telemetry views.',
    bullets: [
      'Multi-session visualization workspace for long race windows.',
      'Control room dashboards for live race strategy and pit planning.',
      'Operational reporting for stints, incidents, and post-race review.',
    ],
    primaryCta: { label: 'Book Endurance Demo', href: '/book?persona=endurance' },
    secondaryCta: { label: 'Join Module Waitlist', href: '/waitlist?persona=endurance' },
  },
];

export const personaBySlug = Object.fromEntries(
  personaPages.map((persona) => [persona.slug, persona]),
) as Record<PersonaPage['slug'], PersonaPage>;
