export interface InsightEntry {
  slug: string;
  title: string;
  intent: string;
  tags: string[];
  summary: string;
  relatedHref: string;
  bodyMdx: string;
}

export const insightEntries: InsightEntry[] = [
  {
    slug: 'telemetry-corner-analysis',
    title: 'Telemetry Corner Analysis for Kart Drivers',
    intent: 'corner telemetry analysis karting',
    tags: ['drivers', 'corners', 'coaching'],
    summary: 'Use entry, apex, and exit trace context to unlock repeatable lap-time gains.',
    relatedHref: '/product#key-corner-replay',
    bodyMdx:
      'Corner analysis is most useful when it gives one clear action. LAP aligns traces with track context so drivers can act quickly.',
  },
  {
    slug: 'session-vs-session-comparison',
    title: 'How Session-vs-Session Comparison Improves Race Pace',
    intent: 'session vs session motorsport analytics',
    tags: ['teams', 'progress', 'comparison'],
    summary: 'Compare sessions with confidence to verify progress and reduce inconsistency.',
    relatedHref: '/product#workflow-coverage',
    bodyMdx:
      'Comparisons expose which changes helped and which added noise, giving coaches and drivers a stable development loop.',
  },
  {
    slug: 'race-strategy-dashboard',
    title: 'Building a Race Strategy Dashboard for Endurance Teams',
    intent: 'race strategy dashboard endurance',
    tags: ['endurance', 'strategy', 'operations'],
    summary: 'Bring strategy calls, pace tracking, and pit timing into one operator-ready view.',
    relatedHref: '/product#race-strategy-dashboard',
    bodyMdx:
      'The race strategy dashboard reduces decision latency by placing stint trends and operational status in one board.',
  },
  {
    slug: 'consistency-scoring-explained',
    title: 'How Consistency Scoring Works in Telemetry Analysis',
    intent: 'consistency scoring lap time variation',
    tags: ['drivers', 'scoring', 'coaching'],
    summary: 'Understand how LAP measures lap-to-lap repeatability and what it reveals about driver control.',
    relatedHref: '/product#workflow-coverage',
    bodyMdx:
      'Consistency scoring quantifies how much lap times vary once outliers are removed. A low standard deviation relative to mean pace indicates strong car control and mental discipline. LAP scores consistency out of 25 points, penalizing sessions where the spread between best and worst valid laps is wide. Drivers who score above 20 typically maintain sub-0.5% coefficient of variation across a stint — the hallmark of a professional setup rhythm.',
  },
  {
    slug: 'tyre-degradation-detection',
    title: 'Detecting Tyre Degradation from Telemetry Data',
    intent: 'tyre degradation cliff detection stint analysis',
    tags: ['endurance', 'tyres', 'strategy'],
    summary: 'Identify tyre cliffs and fade rates automatically by analyzing stint pace progression.',
    relatedHref: '/product#race-strategy-dashboard',
    bodyMdx:
      'Tyre degradation shows up as a systematic pace fade across a stint. LAP compares the average pace of the first and last stints to calculate a fade percentage. A fade above 2% signals moderate degradation; above 5% indicates a tyre cliff. Endurance teams use this data to optimize pit windows — pitting before the cliff avoids the exponential time loss that comes from pushing worn rubber. The stint analysis cards show CV% per stint, making it easy to spot when consistency drops as the tyres go off.',
  },
  {
    slug: 'brake-point-optimization',
    title: 'Optimizing Brake Points with Scatter Analysis',
    intent: 'brake point optimization distance speed scatter',
    tags: ['drivers', 'corners', 'technique'],
    summary: 'Use brake scatter plots to find where you are braking too early or too late for each corner.',
    relatedHref: '/product#key-corner-replay',
    bodyMdx:
      'The brake scatter chart plots braking distance against entry speed for each corner across all laps. Tight clusters indicate repeatable technique; scattered points reveal inconsistency. Drivers who brake later (shorter distance) at higher speed gain time, but only when the scatter is tight. A wide spread at a late brake point means the driver is sometimes overdriving. LAP highlights the best-practice brake point from the fastest clean laps and shows the gap between current average and potential — giving a concrete target to aim for in the next session.',
  },
  {
    slug: 'gg-diagram-reading',
    title: 'Reading a GG Diagram: What Your Lateral and Longitudinal Forces Reveal',
    intent: 'GG diagram g-force lateral longitudinal reading interpretation',
    tags: ['drivers', 'technique', 'coaching'],
    summary: 'Learn to read the GG scatter plot and understand what the shape of your force envelope means.',
    relatedHref: '/product#workflow-coverage',
    bodyMdx:
      'A GG diagram plots lateral G-force (cornering) against longitudinal G-force (acceleration and braking). An ideal trace fills a circular envelope — the tyre friction circle. Most drivers show a diamond or oval shape, meaning they are not combining braking with turning effectively. Rounded corners on the GG plot indicate smooth trail-braking transitions; sharp corners suggest sequential inputs. LAP colors each point by lap so you can see how the envelope evolves as tyres degrade or the driver adapts. Comparing the GG shape between your best and worst laps reveals where the time is lost.',
  },
  {
    slug: 'data-driven-driver-coaching',
    title: 'From Data to Action: A Framework for Driver Coaching',
    intent: 'data driven driver coaching telemetry framework',
    tags: ['coaching', 'teams', 'progress'],
    summary: 'Turn telemetry numbers into clear, actionable coaching points that drivers can apply immediately.',
    relatedHref: '/product#workflow-coverage',
    bodyMdx:
      'Effective coaching bridges the gap between what the data shows and what the driver can change. LAP prioritizes coaching actions by impact: the scoring system identifies which of the four categories (Pace, Consistency, Execution, Robustness) has the biggest gap to potential, then the corner coaching table highlights the specific corners where time is being lost. A good coaching debrief focuses on one or two corners per session, not all of them. Start with the corner that has the highest avg_time_loss_ms and work through entry speed, brake point, and throttle pickup as separate focus areas across consecutive runs.',
  },
  {
    slug: 'weather-impact-analysis',
    title: 'Analyzing Weather Impact on Lap Performance',
    intent: 'weather impact temperature humidity wind lap time',
    tags: ['strategy', 'conditions', 'analysis'],
    summary: 'Quantify how temperature, humidity, and wind affect pace to make better setup and strategy decisions.',
    relatedHref: '/product#race-strategy-dashboard',
    bodyMdx:
      'Track temperature directly affects tyre grip and engine performance. A 10°C rise typically costs 0.3-0.5s per lap in karting through reduced mechanical grip and lower air density. LAP logs weather data alongside each session and plots lap times against temperature, humidity, and wind speed. This correlation reveals your car\u2019s sensitivity to conditions. Teams use this data to adjust tyre pressures, gear ratios, and pit strategy — knowing that afternoon sessions will be faster when the temperature drops. The condition phases feature automatically segments sessions by changing weather, so you compare like with like.',
  },
  {
    slug: 'theoretical-lap-calculation',
    title: 'Understanding the Theoretical Lap and Your Gap to Potential',
    intent: 'theoretical lap best sectors gap potential',
    tags: ['drivers', 'scoring', 'analysis'],
    summary: 'Learn how the theoretical best lap is constructed and what the gap percentage means for your development.',
    relatedHref: '/product#key-corner-replay',
    bodyMdx:
      'The theoretical lap combines the best sector times from different laps into one impossible-but-achievable target. If your best S1 was on lap 3 and best S2 on lap 7, the theoretical time is S1(lap3) + S2(lap7) + S3(best). The gap between this time and your actual best lap reveals unrealized potential. A gap under 1% means you are extracting nearly everything the car has. A gap above 3% means there are clear sector-specific improvements available. LAP shows which sectors contribute most to the gap, giving a prioritized list of where to focus practice laps. Professional drivers typically operate within 0.5-1.5% of their theoretical on familiar tracks.',
  },
];

export const insightTags = Array.from(
  new Set(insightEntries.flatMap((entry) => entry.tags)),
).sort();
