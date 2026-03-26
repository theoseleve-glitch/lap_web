import Link from 'next/link';
import { AchievementsBadges } from '@/components/app/AchievementsBadges';
import { SessionDebrief } from '@/components/app/SessionDebrief';
import { ChartSyncToggle } from '@/components/app/ChartSyncToggle';
import { ShowcaseShell, ShowcaseSurface } from '@/components/showcase/ShowcaseShell';

const normalTabs = ['Overview', 'Timeline', 'Analytics', 'Lap Data'];

const sessionData = {
  title: 'Round 3 / Spa / Driver 12',
  driver: 'Noah Vale',
  track: 'Spa-Francorchamps',
  date: '18 Mar 2026',
  fileName: 'spa-round-3-driver-12.csv',
  kart: 'Sodi Sigma DD2',
  type: 'race',
  conditions: 'dry',
  laps: 18,
  grade: 'A',
  bestLap: '1:33.914',
  avgSpeed: '148 km/h',
  maxSpeed: '236 km/h',
  notes: 'Rear pressures reduced by 0.1 bar after lap 8. Brake migration moved rearward for final run.',
};

const normalScores = {
  pace_score: 24,
  pace_max: 25,
  consistency_score: 22,
  consistency_max: 25,
  execution_score: 18,
  execution_max: 20,
  robustness_score: 14,
  robustness_max: 15,
  adaptation_score: 10,
  strengths: ['Pace', 'Consistency', 'Brake release timing'],
  weaknesses: ['Exit patience at Turn 9', 'Mid-corner minimum speed in sector 3'],
  badges: [
    {
      id: 'pace-master',
      label: 'Pace Master',
      tier: 'gold' as const,
      category: 'pace',
      criteria: 'Hold a 90%+ pace score across an entire race report.',
    },
    {
      id: 'steady-hands',
      label: 'Steady Hands',
      tier: 'silver' as const,
      category: 'consistency',
      criteria: 'Keep lap-to-lap variance below 1.0% across valid laps.',
    },
  ],
};

const normalLaps = [
  { lap_number: 1, lap_time_s: 94.882, is_valid: 1, is_best: 0 },
  { lap_number: 2, lap_time_s: 94.241, is_valid: 1, is_best: 0 },
  { lap_number: 3, lap_time_s: 94.082, is_valid: 1, is_best: 0 },
  { lap_number: 4, lap_time_s: 93.914, is_valid: 1, is_best: 1 },
  { lap_number: 5, lap_time_s: 94.018, is_valid: 1, is_best: 0 },
  { lap_number: 6, lap_time_s: 94.377, is_valid: 1, is_best: 0 },
];

const normalCorners = [
  {
    corner_id: 3,
    available: true,
    direction: 'R' as const,
    coaching_hint: 'Carry less brake pressure past turn-in to rotate sooner.',
    time_loss_total_s: 0.221,
  },
  {
    corner_id: 9,
    available: true,
    direction: 'L' as const,
    coaching_hint: 'Delay throttle pickup until steering angle reduces.',
    time_loss_total_s: 0.158,
  },
  {
    corner_id: 14,
    available: true,
    direction: 'R' as const,
    coaching_hint: 'Use all the exit curb to protect minimum speed.',
    time_loss_total_s: 0.132,
  },
];

const timelineEvents = [
  {
    lap: 1,
    type: 'stint_start',
    severity: 'info',
    description: 'Race stint opened on conservative tire temperature targets.',
    lapTime: '1:34.882',
  },
  {
    lap: 4,
    type: 'pb',
    severity: 'positive',
    description: 'Session best established with the strongest sector 2 of the run.',
    lapTime: '1:33.914',
  },
  {
    lap: 8,
    type: 'warning',
    severity: 'warning',
    description: 'Slight pace fade after traffic. Rear tire temperature climbed above target.',
    lapTime: '1:34.508',
  },
  {
    lap: 12,
    type: 'highlight',
    severity: 'highlight',
    description: 'Recovered rhythm after setup note adjustment and cleaner exits in sector 3.',
    lapTime: '1:34.041',
  },
];

const lapRows = [
  { lap: 1, time: '1:34.882', speed: '146 km/h', max: '231 km/h', brake: '1.93g', accel: '0.91g', valid: 'Valid' },
  { lap: 2, time: '1:34.241', speed: '147 km/h', max: '233 km/h', brake: '1.98g', accel: '0.94g', valid: 'Valid' },
  { lap: 3, time: '1:34.082', speed: '148 km/h', max: '235 km/h', brake: '2.00g', accel: '0.96g', valid: 'Valid' },
  { lap: 4, time: '1:33.914', speed: '148 km/h', max: '236 km/h', brake: '2.02g', accel: '0.97g', valid: 'Best' },
  { lap: 5, time: '1:34.018', speed: '148 km/h', max: '235 km/h', brake: '1.99g', accel: '0.95g', valid: 'Valid' },
];

function gradeTone(grade: string) {
  if (grade.startsWith('A')) return 'border-acid-green text-acid-green';
  if (grade.startsWith('B')) return 'border-cyan-400 text-cyan-400';
  if (grade.startsWith('C')) return 'border-marshal-yellow text-marshal-yellow';
  return 'border-steel text-steel';
}

function scoreDimensions() {
  return [
    { label: 'Pace', score: normalScores.pace_score, max: normalScores.pace_max, color: '#B6FF2E' },
    { label: 'Consistency', score: normalScores.consistency_score, max: normalScores.consistency_max, color: '#00d4ff' },
    { label: 'Execution', score: normalScores.execution_score, max: normalScores.execution_max, color: '#D946EF' },
    { label: 'Robustness', score: normalScores.robustness_score, max: normalScores.robustness_max, color: '#FF6A00' },
    { label: 'Adaptation', score: normalScores.adaptation_score, max: 15, color: '#FFD400' },
  ];
}

function ScoreBreakdownCard() {
  const dimensions = scoreDimensions();
  const total = dimensions.reduce((sum, dimension) => sum + dimension.score, 0);

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-8">
      <h2 className="text-lg font-monument text-chalk mb-1">Score Breakdown</h2>
      <p className="text-steel text-xs font-body mb-4">How the session report builds the final grade</p>

      <div className="mb-6 flex items-center gap-4 border-b border-steel/10 pb-4">
        <div className="text-4xl font-monument text-chalk">{Math.round(total)}</div>
        <div className="text-sm font-body text-steel">/ 100</div>
        <div
          className={`ml-auto flex h-12 w-12 items-center justify-center rounded-lg border-2 font-monument text-xl ${gradeTone(sessionData.grade)}`}
        >
          {sessionData.grade}
        </div>
      </div>

      <div className="space-y-4">
        {dimensions.map((dimension) => {
          const pct = Math.min((dimension.score / dimension.max) * 100, 100);
          return (
            <div key={dimension.label}>
              <div className="mb-1 flex items-center justify-between">
                <span className="font-body text-sm text-chalk">{dimension.label}</span>
                <span className="font-telemetry text-xs text-steel">
                  {dimension.score}/{dimension.max}
                </span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-asphalt">
                <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: dimension.color }} />
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 grid gap-4 border-t border-steel/10 pt-4 sm:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-body text-acid-green">Strengths</h3>
          <ul className="space-y-1">
            {normalScores.strengths.map((item) => (
              <li key={item} className="text-sm font-body text-chalk/85">
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-body text-safety-red">Areas to Improve</h3>
          <ul className="space-y-1">
            {normalScores.weaknesses.map((item) => (
              <li key={item} className="text-sm font-body text-chalk/85">
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function SessionInfoCard() {
  return (
    <div className="space-y-8">
      <div className="bg-concrete rounded-xl border border-steel/10 p-8">
        <h2 className="mb-4 text-lg font-monument text-chalk">Session Info</h2>
        <dl className="space-y-3">
          <MetaRow label="File" value={sessionData.fileName} />
          <MetaRow label="Driver" value={sessionData.driver} />
          <MetaRow label="Track" value={sessionData.track} />
          <MetaRow label="Kart" value={sessionData.kart} />
          <MetaRow label="Type" value={sessionData.type} />
          <MetaRow label="Conditions" value={sessionData.conditions} />
          <MetaRow label="Date" value={sessionData.date} />
          <MetaRow label="Laps" value={String(sessionData.laps)} />
          <div className="border-t border-steel/10 pt-2">
            <dt className="mb-1 text-xs font-body uppercase tracking-wider text-steel">Setup Notes</dt>
            <dd className="whitespace-pre-line text-sm font-body text-chalk/80">{sessionData.notes}</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-xl border border-acid-green/20 bg-concrete p-6">
        <h2 className="mb-4 text-lg font-monument text-acid-green">Best Lap #4</h2>
        <dl className="space-y-3">
          <MetaRow label="Time" value={sessionData.bestLap} highlight />
          <MetaRow label="Avg Speed" value={sessionData.avgSpeed} />
          <MetaRow label="Max Speed" value={sessionData.maxSpeed} />
        </dl>
      </div>

      <div className="rounded-xl border border-steel/10 bg-concrete p-6">
        <h2 className="mb-4 text-lg font-monument text-chalk">Data Quality</h2>
        <ul className="space-y-2">
          {[
            '18 valid laps with full GPS and brake traces.',
            'Track match confidence above 97%.',
            'No missing speed samples on the best-lap window.',
            'Condition grouping stable across the final 12 laps.',
          ].map((item) => (
            <li key={item} className="flex items-start gap-2 text-sm font-body text-steel">
              <span className="mt-0.5 text-acid-green">+</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function MetaRow({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-sm font-body text-steel">{label}</dt>
      <dd className={`text-sm font-telemetry ${highlight ? 'text-acid-green' : 'text-chalk'}`}>{value}</dd>
    </div>
  );
}

function NormalReportHeader() {
  return (
    <div className="rounded-[26px] border border-white/10 bg-[linear-gradient(180deg,rgba(15,15,15,0.96),rgba(7,7,7,0.95))] p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <Link href="/reports-showcase" className="text-sm font-body text-steel transition-colors hover:text-chalk">
              Reports
            </Link>
            <span className="text-steel/60">/</span>
            <span className="text-sm font-body text-steel">Sessions</span>
          </div>
          <h1 className="text-2xl font-monument text-chalk tracking-tight">{sessionData.title}</h1>
          <p className="mt-1 text-sm font-body text-steel">
            {sessionData.driver} • {sessionData.track} • {sessionData.date}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className={`flex h-14 w-14 items-center justify-center rounded-lg border-2 font-monument text-2xl ${gradeTone(sessionData.grade)}`}>
            {sessionData.grade}
          </div>
          <button
            type="button"
            className="rounded-lg border border-steel/20 bg-concrete px-3 py-2 text-sm font-body text-chalk"
          >
            Share
          </button>
          <button
            type="button"
            className="rounded-lg border border-steel/20 bg-concrete px-3 py-2 text-sm font-body text-chalk"
          >
            Export Data
          </button>
          <button
            type="button"
            className="rounded-lg border border-steel/20 bg-concrete px-4 py-2 text-sm font-body text-chalk"
          >
            Focus Mode
          </button>
        </div>
      </div>

      <div className="mt-8 flex items-center gap-1 border-b border-steel/10">
        {normalTabs.map((tab, index) => (
          <div
            key={tab}
            className={`relative px-4 py-2.5 text-sm font-body ${
              index === 0 ? 'text-acid-green' : 'text-steel'
            }`}
          >
            {tab}
            {index === 0 && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-acid-green" />}
          </div>
        ))}
        <div className="ml-auto mb-1">
          <ChartSyncToggle />
        </div>
      </div>
    </div>
  );
}

function TimelineSection() {
  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-6">
      <h2 className="mb-4 text-lg font-monument text-chalk">Session Timeline</h2>
      <div className="mb-4 flex flex-wrap gap-3">
        {[
          ['Total Laps', '18'],
          ['Best Lap', 'L4'],
          ['PBs Set', '3'],
          ['Hot Laps', '7'],
        ].map(([label, value]) => (
          <div key={label} className="min-w-[90px] rounded-lg bg-asphalt px-3 py-2 text-center">
            <div className="text-[10px] font-body uppercase text-steel">{label}</div>
            <div className="text-base font-telemetry text-acid-green">{value}</div>
          </div>
        ))}
      </div>

      <div className="relative pl-8">
        <div className="absolute bottom-0 left-3 top-0 w-0.5 bg-steel/20" />
        {timelineEvents.map((event) => (
          <div key={`${event.lap}-${event.type}`} className="relative mb-3">
            <div
              className={`absolute -left-5 top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border-2 border-asphalt ${
                event.severity === 'positive'
                  ? 'bg-acid-green'
                  : event.severity === 'warning'
                    ? 'bg-marshal-yellow'
                    : event.severity === 'highlight'
                      ? 'bg-gold'
                      : 'bg-cyan-400'
              }`}
            />
            <div className="rounded-r-md border-l-[3px] border-l-acid-green bg-asphalt/60 px-3 py-2">
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm font-semibold text-chalk">Lap {event.lap}</span>
                <span className="text-xs font-telemetry text-steel">{event.lapTime}</span>
              </div>
              <p className="mt-1 text-xs font-body text-steel">{event.description}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LapDataSection() {
  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-6">
      <h2 className="mb-4 text-lg font-monument text-chalk">Lap Data</h2>
      <div className="overflow-hidden rounded-xl border border-steel/10">
        <div className="grid grid-cols-[0.5fr_0.85fr_0.8fr_0.8fr_0.7fr_0.7fr_0.7fr] bg-asphalt px-4 py-3 text-[10px] font-telemetry uppercase tracking-[0.16em] text-steel">
          <span>Lap</span>
          <span>Time</span>
          <span>Avg Speed</span>
          <span>Max Speed</span>
          <span>Brake</span>
          <span>Accel</span>
          <span>Status</span>
        </div>
        {lapRows.map((lap) => (
          <div
            key={lap.lap}
            className="grid grid-cols-[0.5fr_0.85fr_0.8fr_0.8fr_0.7fr_0.7fr_0.7fr] border-t border-steel/10 px-4 py-4 text-sm"
          >
            <span className="font-telemetry text-chalk">{lap.lap}</span>
            <span className={`font-telemetry ${lap.valid === 'Best' ? 'text-acid-green' : 'text-chalk'}`}>{lap.time}</span>
            <span className="font-body text-steel">{lap.speed}</span>
            <span className="font-body text-steel">{lap.max}</span>
            <span className="font-body text-steel">{lap.brake}</span>
            <span className="font-body text-steel">{lap.accel}</span>
            <span className={`font-telemetry ${lap.valid === 'Best' ? 'text-acid-green' : 'text-steel'}`}>{lap.valid}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnalyticsPanel({
  title,
  description,
  bars,
}: {
  title: string;
  description: string;
  bars: number[];
}) {
  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-monument text-chalk">{title}</h3>
          <p className="mt-2 text-sm font-body leading-6 text-steel">{description}</p>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 font-telemetry text-[10px] uppercase tracking-[0.16em] text-steel">
          Chart
        </span>
      </div>
      <div className="mt-5 flex h-28 items-end gap-2 rounded-lg bg-asphalt px-4 py-4">
        {bars.map((bar, index) => (
          <div key={`${title}-${index}`} className="flex-1">
            <div
              className={`rounded-t ${
                index % 4 === 0
                  ? 'bg-acid-green/70'
                  : index % 4 === 1
                    ? 'bg-cyan-400/70'
                    : index % 4 === 2
                      ? 'bg-racing-purple/70'
                      : 'bg-pit-orange/70'
              }`}
              style={{ height: `${bar}%` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function AnalyticsSection() {
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-3">
        <AnalyticsPanel
          title="GPS Track Map"
          description="Track trace panel aligned with the real analytics tab map + sync behavior."
          bars={[24, 36, 42, 51, 44, 60, 74, 68]}
        />
        <AnalyticsPanel
          title="Speed Trace"
          description="Primary speed-vs-distance analysis panel with annotations and lap references."
          bars={[30, 54, 38, 72, 65, 48, 78, 56]}
        />
        <AnalyticsPanel
          title="G-G Diagram"
          description="Grip usage summary for cornering, braking, and traction phases."
          bars={[52, 28, 64, 40, 58, 34, 70, 46]}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <AnalyticsPanel
          title="Delta Time + Pedal Traces"
          description="Time delta, throttle, and brake pressure sequence for the selected lap."
          bars={[16, 24, 38, 42, 58, 66, 74, 82]}
        />
        <AnalyticsPanel
          title="RPM / Gear + Friction Circle"
          description="Powertrain and grip overlays used for execution review."
          bars={[72, 64, 58, 66, 48, 54, 38, 44]}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <AnalyticsPanel
          title="Sector Analysis"
          description="Sector scorecards and pace segmentation by track section."
          bars={[40, 52, 68, 74, 60, 56]}
        />
        <AnalyticsPanel
          title="Lap Distribution"
          description="Session spread, modal pace band, and outlier visibility."
          bars={[22, 38, 64, 80, 62, 40, 26]}
        />
        <AnalyticsPanel
          title="Development Drills"
          description="Recommended drills tied to score weaknesses and corner losses."
          bars={[18, 32, 46, 58, 64, 72, 84]}
        />
      </div>

      <div className="rounded-xl border border-steel/10 bg-concrete p-5">
        <h3 className="text-sm font-monument text-chalk">Session Comparison + Overlay Tools</h3>
        <p className="mt-2 max-w-3xl text-sm font-body leading-6 text-steel">
          Cross-session overlay tools sit below the core chart grid in the real report. This capture preserves the
          comparison-heavy layout without depending on live telemetry endpoints.
        </p>
        <div className="mt-5 grid gap-4 md:grid-cols-4">
          {[
            ['Session A', '-0.22s'],
            ['Session B', '-0.09s'],
            ['Reference Lap', 'Best'],
            ['Drill Focus', 'Exit Phase'],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-white/10 bg-asphalt px-4 py-4">
              <p className="text-[10px] font-telemetry uppercase tracking-[0.16em] text-steel">{label}</p>
              <p className="mt-2 text-lg font-monument text-chalk">{value}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function NormalReportsShowcasePage() {
  return (
    <ShowcaseShell
      eyebrow="Normal Race Report"
      title="Standard session report"
      description="Capture surface for the actual normal report flow: session header, overview, debrief, achievements, timeline, and lap-data review."
      links={[
        { href: '/reports-showcase', label: 'Reports Hub' },
        { href: '/reports-showcase/endurance', label: 'Endurance Report' },
        { href: '/strategy-showcase', label: 'Race Strategy' },
      ]}
    >
      <ShowcaseSurface eyebrow="Header" title="Session report navigation and actions">
        <div id="normal-report-header">
          <NormalReportHeader />
        </div>
      </ShowcaseSurface>

      <ShowcaseSurface eyebrow="Overview" title="Score breakdown, metadata, and coaching summary">
        <div id="normal-report-overview">
          <div className="grid gap-8 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <ScoreBreakdownCard />
            </div>
            <SessionInfoCard />
            <div className="lg:col-span-3 space-y-8">
              <SessionDebrief
                totalScore={88}
                grade="A"
                scores={normalScores}
                laps={normalLaps}
                corners={normalCorners}
              />
              <AchievementsBadges badges={normalScores.badges} />
            </div>
          </div>
        </div>
      </ShowcaseSurface>

      <ShowcaseSurface eyebrow="Analytics" title="Chart-heavy analysis section">
        <div id="normal-report-analytics">
          <AnalyticsSection />
        </div>
      </ShowcaseSurface>

      <ShowcaseSurface eyebrow="Timeline" title="Session timeline review">
        <div id="normal-report-timeline">
          <TimelineSection />
        </div>
      </ShowcaseSurface>

      <ShowcaseSurface eyebrow="Lap Data" title="Performance summary and lap table">
        <div id="normal-report-lap-data">
          <div className="rounded-xl border border-steel/10 bg-concrete p-6">
            <h2 className="mb-4 text-lg font-monument text-chalk">Performance Summary</h2>
            <div className="grid gap-3 sm:grid-cols-4">
              {[
                ['Best Time', '1:33.914'],
                ['Mean Time', '1:34.227'],
                ['Median Time', '1:34.181'],
                ['Consistency', '0.9 CV'],
                ['Total Laps', '18'],
                ['Valid Laps', '16'],
                ['Best Avg Speed', '148 km/h'],
                ['Best Max Speed', '236 km/h'],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-white/10 bg-asphalt p-4">
                  <p className="text-[10px] font-telemetry uppercase tracking-[0.16em] text-steel">{label}</p>
                  <p className="mt-2 text-lg font-monument text-chalk">{value}</p>
                </div>
              ))}
            </div>
            <div className="mt-6">
              <LapDataSection />
            </div>
          </div>
        </div>
      </ShowcaseSurface>
    </ShowcaseShell>
  );
}
