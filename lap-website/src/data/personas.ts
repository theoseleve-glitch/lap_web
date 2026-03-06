/**
 * Persona matrix for content targeting.
 * Each persona has a unique value prop and JTBD. Used by content inventory
 * and page-level targeting to ensure no two pages serve the same audience
 * with the same message.
 */

export interface Persona {
  id: string;
  label: string;
  role: string;
  context: string;
  painPoint: string;
  uniqueValueProp: string;
  jtbd: string;
  entryPage: string;
  primaryCta: string;
}

export const personas: Persona[] = [
  {
    id: 'kart_driver',
    label: 'Kart Driver',
    role: 'Individual kart racer (rental to national level)',
    context: 'Races weekends, has RaceChrono/RaceBox data, no engineer',
    painPoint: 'Cannot read raw telemetry or know what to fix next',
    uniqueValueProp: 'Professional coaching reports from a CSV upload — no data skills needed',
    jtbd: 'After each session, understand which corner phase to fix first and measure my progress',
    entryPage: '/',
    primaryCta: 'Start Free',
  },
  {
    id: 'car_driver',
    label: 'Car Track Day Driver',
    role: 'Amateur car driver doing track days or club racing',
    context: 'Has GPS logger, wants to improve but lacks engineering support',
    painPoint: 'Lap times plateau without knowing where time is lost',
    uniqueValueProp: 'Corner-by-corner coaching that breaks the plateau',
    jtbd: 'Identify the two corners costing the most time and get drills to fix them',
    entryPage: '/product',
    primaryCta: 'Try Demo',
  },
  {
    id: 'junior_coach',
    label: 'Junior Team Coach',
    role: 'Coach or race engineer for a junior driver programme',
    context: 'Manages 3–8 drivers, needs standardised debriefs',
    painPoint: 'Ad-hoc verbal feedback wastes debrief time and is inconsistent',
    uniqueValueProp: 'Automated coaching cards that standardise debriefs across drivers',
    jtbd: 'Give every driver the same quality debrief in 5 minutes instead of 45',
    entryPage: '/customers',
    primaryCta: 'See Results',
  },
  {
    id: 'endurance_strategist',
    label: 'Endurance Strategist',
    role: 'Race strategist for 4h–24h endurance events',
    context: 'Multi-car, multi-driver, real-time pit decisions',
    painPoint: 'Manual timing + radio leads to late pit calls and wasted laps',
    uniqueValueProp: 'Live race strategy dashboard with degradation detection and pit windows',
    jtbd: 'Make pit calls within 1 lap of optimal instead of 3',
    entryPage: '/product',
    primaryCta: 'Book Demo',
  },
  {
    id: 'venue_operator',
    label: 'Kart Venue Operator',
    role: 'Track owner or manager running rental/arrive-and-drive sessions',
    context: 'Wants to upsell telemetry reports to customers, needs zero-staff solution',
    painPoint: 'No way to offer data-driven experiences without hiring engineers',
    uniqueValueProp: 'Autonomous QR reports for every driver — zero staff effort',
    jtbd: 'Offer premium telemetry reports to every customer without adding headcount',
    entryPage: '/contact?plan=b2b',
    primaryCta: 'Contact Sales',
  },
];

export function getPersona(id: string): Persona | undefined {
  return personas.find((p) => p.id === id);
}

export function getPersonasForPage(pageId: string): Persona[] {
  return personas.filter((p) => p.entryPage === pageId || p.entryPage.startsWith(pageId));
}
