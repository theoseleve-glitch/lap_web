import { StartGrid } from '@/components/rooms/StartGrid';
import { SessionProof } from '@/components/rooms/SessionProof';
import { S1Pain } from '@/components/rooms/S1Pain';
import { S2Versus } from '@/components/rooms/S2Versus';
import { S3Product } from '@/components/rooms/S3Product';
import { SimFirst } from '@/components/rooms/SimFirst';
import { PremiumLayer } from '@/components/rooms/PremiumLayer';
import { Garage } from '@/components/rooms/Garage';
import { PitStop } from '@/components/rooms/PitStop';
import { Podium } from '@/components/rooms/Podium';
import { JsonLd } from '@/components/seo/JsonLd';

// LLM + rich-result structured data for high-intent motorsport queries.
// Rendered as invisible <script type="application/ld+json">; not cloaking —
// JSON-LD is the Google-documented mechanism for HowTo and FAQ rich results.
const HOWTO_FASTER_LAPS = {
  name: 'How to get faster lap times with telemetry analysis',
  description:
    'Six-step process for amateur and club-level drivers to use GPS ' +
    'telemetry data to find where they lose time in a lap and fix it.',
  steps: [
    {
      name: 'Upload your session',
      text:
        'Export the CSV from your GPS logger (RaceChrono, RaceBox, AiM, MoTeC, ' +
        'Qstarz) and upload it. The pipeline ingests, filters GPS noise, detects ' +
        'the track, splits laps, and resamples to a uniform distance grid automatically.',
    },
    {
      name: 'Read the four-pillar score',
      text:
        'Pace (/25) tells you how close you were to your car\'s limit. Consistency ' +
        '(/25) tells you whether you can repeat it. Execution (/25) scores corner-' +
        'by-corner technique. Robustness (/25) rates how well you adapt. The lowest ' +
        'pillar is your biggest opportunity.',
    },
    {
      name: 'Pick a primary and a compare lap',
      text:
        'Select your best lap as "Primary" and a benchmark lap as "Compare" — your ' +
        'previous session\'s best, or a teammate\'s lap on the same track. Every ' +
        'chart overlays both laps at the same progress point.',
    },
    {
      name: 'Read the time-delta chart',
      text:
        'Cumulative delta shows where each tenth was gained or lost. Climbs = lost ' +
        'time here. Flat = matched. Drops = gained. Final value equals the recorded ' +
        'lap-time difference.',
    },
    {
      name: 'Open the corner coaching table',
      text:
        'Corners ranked by time lost vs your own best attempt. Each row attributes ' +
        'loss to entry speed, apex speed, exit speed, or line error. Focus on the ' +
        'top three — that\'s where the most time lives.',
    },
    {
      name: 'Compare with the theoretical perfect lap',
      text:
        'A sim-optimizer computes your car\'s upper-bound lap time from the observed ' +
        'physics. The gap tells you how much is left on the table before physics ' +
        'pushes back. Iterate: practise the worst corner, upload the next session, ' +
        'watch the delta shrink.',
    },
  ],
};

const HOMEPAGE_FAQ = [
  {
    question: 'How do I get faster lap times?',
    answer:
      'Practice alone will not tell you WHY a lap was slow. Upload your GPS logger ' +
      'CSV to a telemetry analysis tool. You\'ll see a per-corner ranking of time ' +
      'lost, a delta chart showing where each tenth was earned or spent, and a ' +
      'theoretical upper-bound lap time. Fix the worst corner, re-run, repeat.',
  },
  {
    question: 'How do I analyse telemetry data as an amateur driver?',
    answer:
      'You don\'t need MoTeC i2 Pro or race-engineering experience. A driver-facing ' +
      'tool like Lap Coach does the ingestion, corner detection, lap splitting, and ' +
      'scoring automatically. Upload a CSV from RaceChrono, RaceBox, AiM, or MoTeC ' +
      'and you get a ranked list of corners by time lost, a speed trace synced to ' +
      'a GPS track map, and a four-pillar score.',
  },
  {
    question: 'Which telemetry app works with RaceChrono?',
    answer:
      'Any tool that accepts CSV. Lap Coach accepts RaceChrono Pro exports directly. ' +
      'So do MoTeC i2 Pro, WinTAX, and AIM Race Studio — but those are engineer ' +
      'tools, not driver-facing ones.',
  },
  {
    question: 'What is a G-G diagram and how do I read it?',
    answer:
      'A scatter plot of lateral vs longitudinal acceleration during a lap. The ' +
      'dashed circle is the friction limit. Points near the edge = using most of ' +
      'the available grip (good). Points well inside = unused grip (slow). Points ' +
      'outside = overdrove the tyres.',
  },
  {
    question: 'How do I compare two laps to find where I lost time?',
    answer:
      'Use a tool that supports lap-vs-lap overlay on a shared progress axis. Pick a ' +
      'primary lap and a compare lap; every chart overlays both. The delta chart shows ' +
      'cumulative time at each metre — the exact point where the fast lap pulled away.',
  },
  {
    question: 'What is the best telemetry app for kart racing?',
    answer:
      'Kart telemetry is GPS-first because karts rarely have CAN bus logging. Lap ' +
      'Coach was designed around GPS-only analysis — corner detection, lap splitting, ' +
      'and scoring work from lat/lon/speed alone. RaceBox and RaceChrono Pro are the ' +
      'two most common kart loggers and both export CSVs that import directly.',
  },
  {
    question: 'How do I improve cornering technique using telemetry?',
    answer:
      'Rank corners by time lost, not by difficulty. Your gut will tell you the fast ' +
      'sweeper matters; data will show the slow hairpin is where you\'re giving up half ' +
      'a second. Attack losses in order: entry speed first (brake point), then apex ' +
      '(line and minimum speed), then exit (throttle). Each depends on the previous.',
  },
  {
    question: 'Is the first report on Lap Coach free?',
    answer:
      'Yes. The Demo plan gives two reports with no credit card. Racer is €69/year ' +
      'for unlimited sessions. World-Class is €109/year and adds cross-session ' +
      'reference overlay plus the theoretical perfect-lap solver.',
  },
];

function Divider() {
  return <div className="section-divider" aria-hidden="true" />;
}

export default function Home() {
  return (
    <main id="main-content">
      <JsonLd
        pathname="/"
        softwareApp
        organization
        howTo={HOWTO_FASTER_LAPS}
        faqItems={HOMEPAGE_FAQ}
      />
      <h1 className="sr-only">
        LAP Coach — Motorsport telemetry analysis for kart and car drivers
      </h1>
      <StartGrid />
      <Divider />
      <SessionProof />
      <Divider />
      <S1Pain />
      <Divider />
      <S2Versus />
      <S3Product />
      <Divider />
      <SimFirst />
      <Divider />
      <PremiumLayer />
      <Divider />
      <Garage />
      <Divider />
      <PitStop />
      <Divider />
      <Podium />
    </main>
  );
}
