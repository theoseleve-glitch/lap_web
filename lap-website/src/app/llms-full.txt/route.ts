import { routeMap } from '@/data/route-map';
import { BRAND } from '@/data/brand';
import { insightEntries } from '@/data/insights-cms';

const HEADERS = {
  'Content-Type': 'text/plain; charset=utf-8',
  'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=600',
};

export function GET(): Response {
  const pages = Object.values(routeMap)
    .filter((entry) => !entry.noIndex)
    .map((entry) => {
      const desc = entry.metaDescription ? `\n  ${entry.metaDescription}` : '';
      return `- **${entry.title}** (${entry.path})${desc}`;
    })
    .join('\n');

  const insights = insightEntries
    .map(
      (entry) =>
        `### ${entry.title}\n- Slug: ${entry.slug}\n- Summary: ${entry.summary}\n\n${entry.bodyMdx}`,
    )
    .join('\n\n');

  const content = `# ${BRAND.productName} \u2014 Motorsport Telemetry Analysis Platform

> ${BRAND.positioning}

## Pages

${pages}

## Insights

${insights}

## Glossary

- **LAP**: The product name for the motorsport telemetry analysis SaaS platform built by Lap Coach. Always written in uppercase.
- **Telemetry**: Sensor data recorded during a racing session, including GPS position, speed, acceleration, brake pressure, and steering angle.
- **Session**: A single on-track activity (practice, qualifying, or race) from which telemetry data is captured and uploaded for analysis.
- **Corner**: A defined section of a racing circuit where the driver must reduce speed and change direction. LAP automatically detects corners from GPS data and analyses entry, apex, and exit technique for each one.
- **Pillar Scores**: LAP scores driver performance across four categories (Pace, Consistency, Execution, Robustness), each worth 25 points, totalling 100. These are the four pillars of performance analysis.
- **RaceChrono**: A popular motorsport data-logging app for smartphones that records GPS and OBD/CAN telemetry. LAP ingests RaceChrono CSV exports natively.
- **RaceBox**: A dedicated GPS data-logger device used in motorsport. LAP ingests RaceBox CSV exports natively.

## Pricing

### Demo (Free)
- Upload and analyse up to 3 sessions
- Full 14-stage pipeline with corner detection and scoring
- Speed trace, GPS trace, and GG diagram charts
- No credit card required

### Racer (\u20ac9/mo or \u20ac69/yr)
- Unlimited session uploads and analysis
- Session-vs-session comparison
- Corner coaching table with time-loss rankings
- Priority pipeline processing
- Email support

### World-Class (\u20ac15/mo or \u20ac109/yr)
- Everything in Racer
- Team workspace and multi-driver management
- Race strategy dashboard with stint analysis
- Tyre degradation and pace fade detection
- Export reports (PDF, CSV)
- Dedicated support

## FAQ

**Q: What file formats does LAP accept?**
A: LAP accepts CSV exports from RaceChrono and RaceBox. These are the two most widely used data-logging tools in amateur and club motorsport. AiM and MoTeC format support is on the roadmap.

**Q: How does corner detection work?**
A: LAP uses GPS coordinates and speed traces to automatically identify corners on any circuit. The algorithm detects lateral acceleration peaks and cross-references with the GPS track shape to assign entry, apex, and exit zones. No manual circuit configuration is needed for standard tracks.

**Q: What are the four scoring pillars?**
A: Pace (how fast you are relative to your theoretical best lap), Consistency (lap-to-lap repeatability measured by coefficient of variation), Execution (how well you exploit each corner \u2014 entry speed, brake point, throttle pickup), and Robustness (how well your performance holds up across a full session including tyre wear and track evolution). Each pillar is scored out of 25, giving a total out of 100.

**Q: Can I compare two sessions from different days or circuits?**
A: Yes. LAP\u2019s session comparison aligns laps by distance rather than time, so you can compare laps from different days on the same circuit. Cross-circuit comparison is not supported because the track geometry differs. The comparison view overlays speed traces, GG diagrams, and corner statistics side-by-side.
`;

  return new Response(content, { headers: HEADERS });
}
