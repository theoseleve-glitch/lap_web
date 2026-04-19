import type { ReactNode } from 'react';
import { StatCard } from '@/components/app/StatCard';
import { ShowcaseShell, ShowcaseSurface } from '@/components/showcase/ShowcaseShell';
import { PageIntro } from '@/components/ui/PageIntro';

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-steel/20 bg-concrete p-4">
      <h3 className="font-telemetry text-xs uppercase tracking-wider text-steel">{title}</h3>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function TableCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-steel/20 bg-concrete">
      <div className="border-b border-steel/20 px-4 py-3">
        <h3 className="font-telemetry text-xs uppercase tracking-wider text-steel">{title}</h3>
      </div>
      <div className="overflow-x-auto">{children}</div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="mb-1 font-telemetry text-[11px] uppercase tracking-[0.08em] text-steel">{label}</p>
      <div className="rounded border border-steel/30 bg-asphalt px-3 py-2 text-sm text-chalk">{value}</div>
    </div>
  );
}

function Chip({ label, tone = 'default' }: { label: string; tone?: 'default' | 'green' | 'gold' | 'red' }) {
  const className =
    tone === 'green'
      ? 'border-acid-green/30 bg-acid-green/10 text-acid-green'
      : tone === 'gold'
        ? 'border-gold/30 bg-gold/10 text-gold'
        : tone === 'red'
          ? 'border-safety-red/30 bg-safety-red/10 text-safety-red'
          : 'border-steel/30 bg-steel/10 text-steel';
  return (
    <span className={`inline-flex rounded border px-2 py-0.5 font-telemetry text-[10px] uppercase tracking-[0.12em] ${className}`}>
      {label}
    </span>
  );
}

function DashboardEmptyStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Dashboard"
        subtitle="Empty-state onboarding with upload-first activation."
        actions={<span className="rounded bg-gold px-4 py-2 font-telemetry text-sm text-white">+ Upload Session</span>}
      />
      <div className="rounded-[24px] border border-acid-green/20 bg-[linear-gradient(135deg,rgba(182,255,46,0.08),rgba(8,8,8,0.96))] p-6">
        <p className="font-telemetry text-xs uppercase tracking-[0.18em] text-acid-green">Welcome to LAP</p>
        <h3 className="mt-3 font-monument text-2xl text-chalk">Start with your first telemetry upload</h3>
        <p className="mt-3 max-w-2xl text-sm text-steel">
          Import a CSV from RaceChrono, AiM, MoTeC, or VBOX to unlock your first coaching report,
          session comparison, and leaderboard profile.
        </p>
        <div className="mt-5 flex gap-3">
          <span className="rounded bg-gold px-4 py-2 font-telemetry text-xs uppercase text-white">Upload Now</span>
          <span className="rounded border border-steel/30 px-4 py-2 font-telemetry text-xs uppercase text-steel">How It Works</span>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Step 1">
          <p className="text-sm text-steel">Upload a session and map your corners if the track is new.</p>
        </Card>
        <Card title="Step 2">
          <p className="text-sm text-steel">Review the 4-pillar coaching score and debrief guidance.</p>
        </Card>
        <Card title="Step 3">
          <p className="text-sm text-steel">Compare runs, track progression, and follow your leaderboard rank.</p>
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Feature Card">
          <div className="h-36 rounded bg-asphalt" />
        </Card>
        <Card title="Feature Card">
          <div className="h-36 rounded bg-asphalt" />
        </Card>
        <Card title="Feature Card">
          <div className="h-36 rounded bg-asphalt" />
        </Card>
      </div>
    </div>
  );
}

function DashboardLiveStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Dashboard"
        subtitle="Populated overview with session trends, activation checklist, and recent activity."
        actions={<div className="flex gap-2"><Chip label="This Month" tone="green" /><Chip label="Share Summary" /></div>}
      />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-7">
        <StatCard label="Sessions" value={148} />
        <StatCard label="Drivers" value={12} />
        <StatCard label="Tracks" value={9} />
        <StatCard label="PB Alerts" value={16} trend="up" />
        <StatCard label="Avg Score" value={92} />
        <StatCard label="Best Lap" value="1:01.772" />
        <StatCard label="Compare Ready" value={34} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card title="Score Trend + Lap Time">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="h-48 rounded bg-asphalt" />
            <div className="h-48 rounded bg-asphalt" />
          </div>
        </Card>
        <Card title="Last Session">
          <div className="space-y-3 text-sm text-steel">
            <p className="font-monument text-lg text-chalk">Night stint replay</p>
            <p>Spa-Francorchamps . 24 laps . Grade A</p>
            <div className="flex gap-2"><Chip label="Open Session" tone="green" /><Chip label="Compare" /><Chip label="Visualize" /></div>
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card title="Activation Checklist">
          <div className="space-y-3">
            {['Upload your first session', 'Review a coaching report', 'Set your display name', 'Compare two sessions'].map((item, index) => (
              <div key={item} className="flex items-center justify-between rounded border border-steel/20 bg-asphalt px-3 py-2 text-sm">
                <span className="text-chalk">{item}</span>
                <Chip label={index < 2 ? 'Done' : 'Next'} tone={index < 2 ? 'green' : 'gold'} />
              </div>
            ))}
          </div>
        </Card>
        <TableCard title="Recent Sessions">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/20">
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Session</th>
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Track</th>
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Grade</th>
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Delta</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-chalk">Night stint replay</td>
                <td className="px-4 py-3 text-sm text-chalk">Spa</td>
                <td className="px-4 py-3 text-sm text-acid-green">A</td>
                <td className="px-4 py-3 text-sm text-acid-green">-0.412</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-sm text-chalk">Qualifying push</td>
                <td className="px-4 py-3 text-sm text-chalk">Barcelona</td>
                <td className="px-4 py-3 text-sm text-gold">S</td>
                <td className="px-4 py-3 text-sm text-safety-red">+0.031</td>
              </tr>
            </tbody>
          </table>
        </TableCard>
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_0.7fr]">
        <Card title="Achievements Block">
          <div className="grid grid-cols-4 gap-3">
            <div className="h-24 rounded bg-asphalt" />
            <div className="h-24 rounded bg-asphalt" />
            <div className="h-24 rounded bg-asphalt" />
            <div className="h-24 rounded bg-asphalt" />
          </div>
        </Card>
        <Card title="NPS Survey">
          <p className="text-sm text-steel">How likely are you to recommend LAP to another driver?</p>
          <div className="mt-3 grid grid-cols-6 gap-2">
            {['5', '6', '7', '8', '9', '10'].map((score) => (
              <div key={score} className="rounded border border-steel/20 px-3 py-2 text-center font-telemetry text-sm text-chalk">{score}</div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function SessionsListStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Sessions"
        subtitle="List, calendar, and grouped views with filters, bulk actions, and archive states."
        actions={<div className="flex gap-2"><Chip label="List" tone="green" /><Chip label="Calendar" /><Chip label="Grouped" /></div>}
      />
      <div className="flex flex-wrap gap-2">
        <Chip label="Active" tone="green" />
        <Chip label="Archived" />
        <Chip label="All" />
        <Chip label="Columns" />
        <Chip label="Filters" />
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Visible Sessions" value={48} />
        <StatCard label="Archived" value={9} />
        <StatCard label="Bulk Selected" value={3} />
        <StatCard label="Compare Ready" value={22} />
      </div>
      <div className="rounded-lg border border-gold/20 bg-gold/5 px-4 py-3 text-sm text-steel">
        Bulk action bar open: Compare, Archive, and Delete for 3 selected sessions.
      </div>
      <TableCard title="Primary Table View">
        <table className="w-full">
          <thead>
            <tr className="border-b border-steel/20">
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Session</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Track</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Score</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">State</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-steel/10">
              <td className="px-4 py-3 text-sm text-chalk">Night stint replay</td>
              <td className="px-4 py-3 text-sm text-chalk">Spa</td>
              <td className="px-4 py-3 text-sm text-chalk">Mia Duval</td>
              <td className="px-4 py-3 text-sm text-acid-green">95</td>
              <td className="px-4 py-3 text-sm text-steel">Active</td>
            </tr>
            <tr>
              <td className="px-4 py-3 text-sm text-chalk">Wet adaptation set</td>
              <td className="px-4 py-3 text-sm text-chalk">Spa</td>
              <td className="px-4 py-3 text-sm text-chalk">Noah Vale</td>
              <td className="px-4 py-3 text-sm text-gold">88</td>
              <td className="px-4 py-3 text-sm text-steel">Archived</td>
            </tr>
          </tbody>
        </table>
      </TableCard>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Calendar View">
          <div className="h-64 rounded bg-asphalt" />
        </Card>
        <Card title="Grouped Events">
          <div className="space-y-3">
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Spa Sprint Camp . 5 sessions</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Barcelona Prep . 3 sessions</div>
          </div>
        </Card>
        <Card title="Filtered Empty State">
          <p className="text-sm text-steel">No sessions match current filters. Clear date range or include archived runs.</p>
        </Card>
      </div>
    </div>
  );
}

function SessionsUploadFormStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Upload Session" subtitle="Import form with queue, metadata, endurance options, and structured errors." />
      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Card title="Upload Queue">
          <div className="rounded border border-dashed border-acid-green/40 bg-asphalt p-6 text-center text-sm text-steel">
            Drag and drop CSV files or browse for RaceChrono, AiM, MoTeC, or VBOX exports.
          </div>
          <div className="mt-4 space-y-2">
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-2 text-sm text-chalk">night-stint-17.csv . Ready</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-2 text-sm text-chalk">qualifying-push.csv . Ready</div>
          </div>
        </Card>
        <Card title="Metadata + Endurance Options">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Driver" value="Mia Duval" />
            <Field label="Track" value="Spa-Francorchamps" />
            <Field label="Kart" value="CRG KT2 #14" />
            <Field label="Session Type" value="Practice" />
            <Field label="Pit Threshold" value="40 sec" />
            <Field label="Joker Laps" value="Lap 4, Lap 11" />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Chip label="Endurance Drivers: Mia" tone="green" />
            <Chip label="Endurance Drivers: Noah" />
            <Chip label="Wet Session" />
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <Card title="Import Errors">
          <div className="space-y-3 text-sm text-steel">
            <div className="rounded border border-safety-red/25 bg-safety-red/5 px-3 py-3">
              Unknown GPS column detected. Use RaceChrono export preset or map headers manually.
            </div>
            <div className="rounded border border-gold/25 bg-gold/5 px-3 py-3">
              Corner definitions required for a new track before analytics can be generated.
            </div>
          </div>
        </Card>
        <Card title="Submit Row">
          <div className="space-y-3">
            <span className="inline-flex rounded bg-gold px-4 py-2 font-telemetry text-xs uppercase text-white">Analyze Sessions</span>
            <span className="inline-flex rounded border border-steel/30 px-4 py-2 font-telemetry text-xs uppercase text-steel">Save as Draft</span>
          </div>
        </Card>
      </div>
    </div>
  );
}

function SessionsUploadFlowStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Upload Processing Flow" subtitle="Progress milestones, corner editor branch, and endurance report drilldown." />
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card title="Progress State">
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-sm"><span className="text-steel">Upload</span><span className="text-chalk">100%</span></div>
              <div className="mt-1 h-2 rounded-full bg-asphalt"><div className="h-full w-full rounded-full bg-acid-green" /></div>
            </div>
            <div>
              <div className="flex justify-between text-sm"><span className="text-steel">Parse + Normalize</span><span className="text-chalk">82%</span></div>
              <div className="mt-1 h-2 rounded-full bg-asphalt"><div className="h-full w-[82%] rounded-full bg-gold" /></div>
            </div>
            <div>
              <div className="flex justify-between text-sm"><span className="text-steel">Coaching Report</span><span className="text-chalk">Pending</span></div>
              <div className="mt-1 h-2 rounded-full bg-asphalt"><div className="h-full w-[22%] rounded-full bg-steel" /></div>
            </div>
          </div>
        </Card>
        <Card title="Milestones">
          <div className="space-y-3 text-sm text-steel">
            <div className="rounded border border-acid-green/20 bg-acid-green/5 px-3 py-3">File received and normalized.</div>
            <div className="rounded border border-acid-green/20 bg-acid-green/5 px-3 py-3">Track matched to existing Spa profile.</div>
            <div className="rounded border border-gold/20 bg-gold/5 px-3 py-3">Awaiting corner confirmation for bus-stop split.</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3">Endurance report generation queued for team summary.</div>
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Corner Editor Branch">
          <div className="h-56 rounded bg-asphalt" />
        </Card>
        <Card title="Endurance Processing">
          <div className="space-y-3 text-sm text-steel">
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3">Driver stints mapped</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3">Pit windows inferred</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3">Team report staging</div>
          </div>
        </Card>
        <Card title="Completed">
          <p className="text-sm text-steel">Single-session imports redirect to session detail. Batch imports show a compact completion summary.</p>
        </Card>
      </div>
    </div>
  );
}

function SessionOverviewStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Night Stint Replay"
        subtitle="Session detail overview with coaching score, editable info, debrief, and achievements."
        actions={<div className="flex gap-2"><Chip label="Overview" tone="green" /><Chip label="Share" /><Chip label="Focus Mode" /><Chip label="Delete" tone="red" /></div>}
      />
      <div className="flex flex-wrap gap-2">
        <Chip label="Timeline" />
        <Chip label="Analytics" />
        <Chip label="Lap Data" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card title="Score Breakdown">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatCard label="Braking" value={94} />
            <StatCard label="Entry" value={88} />
            <StatCard label="Rotation" value={90} />
            <StatCard label="Exit" value={95} />
          </div>
        </Card>
        <Card title="Best Lap + Data Quality">
          <div className="space-y-3 text-sm text-steel">
            <p className="text-chalk">Best lap: 1:02.441 on lap 17</p>
            <p className="text-chalk">GPS quality: Excellent</p>
            <p className="text-chalk">Missing samples: 0.4%</p>
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Strengths + Weaknesses">
          <div className="space-y-3 text-sm text-steel">
            <div className="rounded border border-acid-green/20 bg-acid-green/5 px-3 py-3">Strong throttle commitment through sector 2 exits.</div>
            <div className="rounded border border-safety-red/20 bg-safety-red/5 px-3 py-3">Brake release still abrupt into the bus stop.</div>
          </div>
        </Card>
        <Card title="Session Info">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Driver" value="Mia Duval" />
            <Field label="Track" value="Spa-Francorchamps" />
            <Field label="Weather" value="Cool dry night" />
            <Field label="Kart" value="CRG KT2 #14" />
          </div>
        </Card>
        <Card title="Driving Style">
          <div className="h-56 rounded bg-asphalt" />
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <Card title="Debrief">
          <p className="text-sm text-steel">
            Cleanest lap window of the set, with consistent commitment through Pouhon and stable tire state on exit.
            Main opportunity remains brake migration into the final chicane.
          </p>
        </Card>
        <Card title="Achievements">
          <div className="grid grid-cols-4 gap-2">
            <div className="h-20 rounded bg-asphalt" />
            <div className="h-20 rounded bg-asphalt" />
            <div className="h-20 rounded bg-asphalt" />
            <div className="h-20 rounded bg-asphalt" />
          </div>
        </Card>
      </div>
    </div>
  );
}

function SessionAnalyticsStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Session Analytics"
        subtitle="Telemetry-heavy tab with map, overlays, sector tools, and development drills."
        actions={<div className="flex gap-2"><Chip label="Dark Theme" tone="green" /><Chip label="Chart Sync" /><Chip label="Overlay Lap 03" tone="gold" /></div>}
      />
      <div className="flex flex-wrap gap-2">
        <Chip label="GPS Map" tone="green" />
        <Chip label="Speed Trace" />
        <Chip label="G-G" />
        <Chip label="Delta" />
        <Chip label="Pedals" />
        <Chip label="Tires" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.85fr]">
        <Card title="GPS Map">
          <div className="h-64 rounded bg-[radial-gradient(circle_at_35%_30%,rgba(0,212,255,0.16),transparent_35%),linear-gradient(180deg,#101010,#050505)]" />
        </Card>
        <Card title="Speed Trace + Minimap">
          <div className="h-64 rounded bg-asphalt" />
        </Card>
        <Card title="Sector Panel">
          <div className="space-y-3 text-sm text-steel">
            <div className="flex justify-between"><span>S1</span><span className="text-chalk">18.441</span></div>
            <div className="flex justify-between"><span>S2</span><span className="text-chalk">21.003</span></div>
            <div className="flex justify-between"><span>S3</span><span className="text-chalk">22.997</span></div>
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr]">
        <Card title="G-G Diagram">
          <div className="h-52 rounded bg-asphalt" />
        </Card>
        <Card title="Time Delta">
          <div className="h-52 rounded bg-asphalt" />
        </Card>
        <Card title="Conditional Traces">
          <div className="space-y-3">
            <div className="h-14 rounded bg-asphalt" />
            <div className="h-14 rounded bg-asphalt" />
            <div className="h-14 rounded bg-asphalt" />
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <Card title="Lap Overlay + Distribution">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="h-40 rounded bg-asphalt" />
            <div className="h-40 rounded bg-asphalt" />
          </div>
        </Card>
        <Card title="Development Drills">
          <div className="space-y-3 text-sm text-steel">
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3">Brake release smoothing into final chicane</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3">Throttle timing out of La Source</div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function CompareHubStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Compare" subtitle="Hub with quick-start cards and entitlement gating." />
      <div className="rounded-lg border border-gold/20 bg-gold/5 px-4 py-3 text-sm text-steel">
        Upgrade banner state: advanced comparison is locked until team plan entitlement is active.
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Session Quick Start">
          <div className="space-y-3">
            <div className="rounded border border-steel/30 bg-asphalt px-4 py-3 text-sm text-steel">Search or pick Session A</div>
            <div className="rounded border border-steel/30 bg-asphalt px-4 py-3 text-sm text-steel">Search or pick Session B</div>
            <div className="flex gap-2"><Chip label="Compare Sessions" tone="green" /><Chip label="Saved Templates" /></div>
          </div>
        </Card>
        <Card title="Driver Quick Start">
          <div className="space-y-3">
            <div className="rounded border border-steel/30 bg-asphalt px-4 py-3 text-sm text-steel">Select Driver A</div>
            <div className="rounded border border-steel/30 bg-asphalt px-4 py-3 text-sm text-steel">Select Driver B</div>
            <div className="flex gap-2"><Chip label="Compare Drivers" tone="green" /><Chip label="Upgrade" tone="gold" /></div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function CompareDriversStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Driver Comparison"
        subtitle="A/B selectors, radar, trends, and summary statistics."
        actions={<div className="flex gap-2"><Chip label="Swap Drivers" /><Chip label="A vs B" tone="green" /></div>}
      />
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Driver A">
          <div className="space-y-2 text-sm text-steel">
            <p className="font-monument text-lg text-chalk">Mia Duval</p>
            <Chip label="Level 9" tone="gold" />
          </div>
        </Card>
        <Card title="Driver B">
          <div className="space-y-2 text-sm text-steel">
            <p className="font-monument text-lg text-chalk">Noah Vale</p>
            <Chip label="Level 11" tone="gold" />
          </div>
        </Card>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Score A" value={93} />
        <StatCard label="Score B" value={91} />
        <StatCard label="PB Delta" value="-0.136" />
        <StatCard label="Sessions Gap" value={16} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Radar">
          <div className="h-56 rounded bg-asphalt" />
        </Card>
        <Card title="Trend Chart">
          <div className="h-56 rounded bg-asphalt" />
        </Card>
        <TableCard title="Summary Statistics">
          <table className="w-full">
            <tbody>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-steel">Best Lap</td>
                <td className="px-4 py-3 text-sm text-chalk">1:01.908 vs 1:01.772</td>
              </tr>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-steel">Avg Score</td>
                <td className="px-4 py-3 text-sm text-chalk">93 vs 91</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-sm text-steel">Consistency</td>
                <td className="px-4 py-3 text-sm text-chalk">High vs Medium</td>
              </tr>
            </tbody>
          </table>
        </TableCard>
      </div>
    </div>
  );
}

function CompareSessionsStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Session Comparison"
        subtitle="Session A/B selectors, saved templates, chart rail, and lap tables."
        actions={<div className="flex gap-2"><Chip label="Save Template" tone="green" /><Chip label="Swap Sessions" /></div>}
      />
      <div className="flex flex-wrap gap-2">
        <Chip label="Spa Sprint Baseline" tone="gold" />
        <Chip label="Qualifying A/B" />
        <Chip label="Night vs Day" />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Session A">
          <div className="space-y-2 text-sm text-steel">
            <p className="font-monument text-lg text-chalk">Night stint replay</p>
            <p>Spa . Mia Duval . 24 laps</p>
          </div>
        </Card>
        <Card title="Session B">
          <div className="space-y-2 text-sm text-steel">
            <p className="font-monument text-lg text-chalk">Qualifying push</p>
            <p>Spa . Mia Duval . 8 laps</p>
          </div>
        </Card>
      </div>
      <div className="rounded-[24px] border border-acid-green/20 bg-[linear-gradient(135deg,rgba(182,255,46,0.08),rgba(8,8,8,0.96))] p-6">
        <p className="font-telemetry text-xs uppercase tracking-[0.18em] text-acid-green">Total Score Delta</p>
        <h3 className="mt-3 font-monument text-3xl text-chalk">+3.8 points</h3>
        <p className="mt-2 text-sm text-steel">Improvement driven by cleaner braking and faster throttle pick-up out of slow corners.</p>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Scoring Radar">
          <div className="h-56 rounded bg-asphalt" />
        </Card>
        <Card title="Compare Chart Rail">
          <div className="space-y-3">
            <div className="h-14 rounded bg-asphalt" />
            <div className="h-14 rounded bg-asphalt" />
            <div className="h-14 rounded bg-asphalt" />
            <div className="h-14 rounded bg-asphalt" />
          </div>
        </Card>
        <Card title="Metadata Cards">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Weather</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Track Temp</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Tire State</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Fuel Load</div>
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <TableCard title="Lap Comparison Table">
          <table className="w-full">
            <thead>
              <tr className="border-b border-steel/20">
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Lap</th>
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">A</th>
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">B</th>
                <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Delta</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-chalk">17</td>
                <td className="px-4 py-3 text-sm text-chalk">1:02.441</td>
                <td className="px-4 py-3 text-sm text-chalk">1:02.772</td>
                <td className="px-4 py-3 text-sm text-acid-green">-0.331</td>
              </tr>
            </tbody>
          </table>
        </TableCard>
        <TableCard title="Individual Lap Tables">
          <table className="w-full">
            <tbody>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-steel">Best braking zone</td>
                <td className="px-4 py-3 text-sm text-chalk">Lap 17</td>
              </tr>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-steel">Best exit delta</td>
                <td className="px-4 py-3 text-sm text-chalk">Lap 03</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-sm text-steel">Corner detail</td>
                <td className="px-4 py-3 text-sm text-chalk">Bus Stop</td>
              </tr>
            </tbody>
          </table>
        </TableCard>
      </div>
    </div>
  );
}

function LeaderboardStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Leaderboard" subtitle="Ranked results with track and driver filters, badges, and empty states." />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Ranked Drivers" value={38} />
        <StatCard label="Tracks" value={9} />
        <StatCard label="Top Grade" value="S" />
        <StatCard label="Filter Matches" value={12} />
      </div>
      <div className="flex gap-3">
        <div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Filter by driver or track...</div>
        <div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">Spa</div>
        <div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">Dry only</div>
      </div>
      <TableCard title="Rankings">
        <table className="w-full">
          <thead>
            <tr className="border-b border-steel/20">
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Rank</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">PB</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Grade</th>
              <th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Conditions</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-steel/10">
              <td className="px-4 py-3 text-sm text-chalk">1</td>
              <td className="px-4 py-3 text-sm text-chalk">Noah Vale</td>
              <td className="px-4 py-3 text-sm text-acid-green">1:01.772</td>
              <td className="px-4 py-3 text-sm text-gold">S</td>
              <td className="px-4 py-3 text-sm text-steel">Dry</td>
            </tr>
            <tr>
              <td className="px-4 py-3 text-sm text-chalk">2</td>
              <td className="px-4 py-3 text-sm text-chalk">Mia Duval</td>
              <td className="px-4 py-3 text-sm text-chalk">1:01.908</td>
              <td className="px-4 py-3 text-sm text-acid-green">A</td>
              <td className="px-4 py-3 text-sm text-steel">Mixed</td>
            </tr>
          </tbody>
        </table>
      </TableCard>
      <div className="rounded-lg border border-steel/20 bg-concrete px-4 py-3 text-sm text-steel">
        Filtered-empty state can replace the table when no entries match the selected driver, track, or conditions.
      </div>
    </div>
  );
}

function KartsListStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="Karts"
        subtitle="Inventory list with sorting, delete confirm, and empty-state handling."
        actions={<span className="rounded bg-gold px-4 py-2 font-telemetry text-sm text-white">+ Add Kart</span>}
      />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Karts" value={7} />
        <StatCard label="Active" value={5} />
        <StatCard label="Sessions Linked" value={148} />
        <StatCard label="Needs Notes" value={2} />
      </div>
      <div className="flex gap-3">
        <div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Search karts...</div>
        <div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">Sort: Recent</div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {['CRG KT2 #14', 'Sodi STV #03'].map((kart, index) => (
          <div key={kart} className="rounded-lg border border-steel/20 bg-concrete p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-monument text-lg text-chalk">{kart}</p>
                <p className="mt-1 text-sm text-steel">{index === 0 ? 'Race kart' : 'Wet setup kart'}</p>
              </div>
              <Chip label={`${index === 0 ? 38 : 22} sessions`} tone="gold" />
            </div>
            <div className="mt-4 grid grid-cols-3 gap-3">
              <div><span className="block font-telemetry text-[10px] text-steel/60">ENGINE</span><span className="text-sm text-chalk">KT2</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">CHASSIS</span><span className="text-sm text-chalk">{index === 0 ? 'CRG' : 'Sodi'}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">STATE</span><span className="text-sm text-chalk">Active</span></div>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <span className="rounded border border-steel/30 px-3 py-2 font-telemetry text-xs uppercase text-chalk">Details -></span>
              <span className="rounded border border-safety-red/30 bg-safety-red/5 px-3 py-2 font-telemetry text-xs uppercase text-safety-red">
                {index === 0 ? 'Confirm Delete' : 'Delete'}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Search Empty State">
          <p className="text-sm text-steel">No karts match "Birel". Clear search or create a custom kart profile.</p>
        </Card>
        <Card title="True Empty State">
          <p className="text-sm text-steel">No karts yet. Add your first kart to link setup history and session context.</p>
        </Card>
      </div>
    </div>
  );
}

function KartsNewStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="New Kart"
        subtitle="Preset catalogue mode and custom form mode in the same creation route."
        actions={<div className="flex gap-2"><Chip label="Catalogue" tone="green" /><Chip label="Custom" /></div>}
      />
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card title="Catalogue Mode">
          <div className="flex flex-wrap gap-2">
            <Chip label="Rental" />
            <Chip label="Sprint" tone="green" />
            <Chip label="Endurance" />
          </div>
          <div className="mt-4 space-y-2">
            <div className="rounded border border-acid-green/30 bg-acid-green/5 px-3 py-3 text-sm text-chalk">CRG KT2 preset</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Sodi STV preset</div>
            <div className="rounded border border-steel/20 bg-asphalt px-3 py-3 text-sm text-chalk">Birel N35 preset</div>
          </div>
        </Card>
        <Card title="Custom Form Mode">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Kart Name" value="Prototype Chassis 07" />
            <Field label="Category" value="Sprint" />
            <Field label="Chassis" value="Custom frame" />
            <Field label="Engine" value="KT2" />
            <Field label="Axle" value="Medium" />
            <Field label="Tires" value="MG Red" />
          </div>
          <div className="mt-4 rounded border border-safety-red/25 bg-safety-red/5 px-3 py-3 text-sm text-steel">
            Mutation error state: a kart with this display name already exists.
          </div>
          <div className="mt-4 flex gap-2">
            <span className="rounded bg-gold px-4 py-2 font-telemetry text-xs uppercase text-white">Save Kart</span>
            <span className="rounded border border-steel/30 px-4 py-2 font-telemetry text-xs uppercase text-steel">Pending...</span>
          </div>
        </Card>
      </div>
    </div>
  );
}

function KartDetailStage() {
  return (
    <div className="space-y-6">
      <PageIntro
        title="CRG KT2 #14"
        subtitle="Kart detail with inline edit, delete confirm, stats, and notes."
        actions={<div className="flex gap-2"><Chip label="Edit" tone="green" /><Chip label="Delete" tone="red" /></div>}
      />
      <div className="rounded-lg border border-safety-red/25 bg-safety-red/5 px-4 py-3 text-sm text-steel">
        Delete confirmation open: 38 sessions are linked to this kart profile.
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Inline Edit Form">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Kart Name" value="CRG KT2 #14" />
            <Field label="Category" value="Race kart" />
            <Field label="Chassis" value="CRG" />
            <Field label="Engine" value="KT2" />
          </div>
        </Card>
        <Card title="Stats">
          <div className="grid grid-cols-2 gap-4">
            <StatCard label="Sessions" value={38} />
            <StatCard label="Drivers" value={4} />
            <StatCard label="PB" value="1:01.772" />
            <StatCard label="Wet Runs" value={6} />
          </div>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <TableCard title="Kart Details">
          <table className="w-full">
            <tbody>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-steel">Axle</td>
                <td className="px-4 py-3 text-sm text-chalk">Medium</td>
              </tr>
              <tr className="border-b border-steel/10">
                <td className="px-4 py-3 text-sm text-steel">Tires</td>
                <td className="px-4 py-3 text-sm text-chalk">MG Red</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-sm text-steel">Introduced</td>
                <td className="px-4 py-3 text-sm text-chalk">2024 Season</td>
              </tr>
            </tbody>
          </table>
        </TableCard>
        <Card title="Notes">
          <p className="text-sm text-steel">
            Stable baseline kart used for dry reference sessions. Strong front bite, slightly nervous on worn rears.
          </p>
        </Card>
      </div>
    </div>
  );
}

export default function CoachSectionsShowcasePage() {
  return (
    <ShowcaseShell
      eyebrow="Coach Sections"
      title="Dashboard, sessions, compare, leaderboard, and karts"
      description="Detailed capture page for the remaining primary user-facing sections in the coach and engineer flows."
      links={[
        { href: '/core-sections-showcase', label: 'Core Sections' },
        { href: '/strategy-showcase', label: 'Strategy' },
        { href: '/reports-showcase', label: 'Reports' },
      ]}
    >
      <ShowcaseSurface eyebrow="Dashboard" title="Empty onboarding state">
        <div id="coach-showcase-dashboard-empty"><DashboardEmptyStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Dashboard" title="Populated overview state">
        <div id="coach-showcase-dashboard-live"><DashboardLiveStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Sessions" title="List, calendar, and grouped workspace">
        <div id="coach-showcase-sessions-list"><SessionsListStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Sessions Upload" title="Form and import setup">
        <div id="coach-showcase-sessions-upload-form"><SessionsUploadFormStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Sessions Upload" title="Progress and processing branches">
        <div id="coach-showcase-sessions-upload-flow"><SessionsUploadFlowStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Session Detail" title="Overview tab">
        <div id="coach-showcase-session-overview"><SessionOverviewStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Session Detail" title="Analytics tab">
        <div id="coach-showcase-session-analytics"><SessionAnalyticsStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Compare" title="Hub">
        <div id="coach-showcase-compare-hub"><CompareHubStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Compare Drivers" title="Driver A/B comparison">
        <div id="coach-showcase-compare-drivers"><CompareDriversStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Compare Sessions" title="Session A/B comparison">
        <div id="coach-showcase-compare-sessions"><CompareSessionsStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Leaderboard" title="Rankings and filters">
        <div id="coach-showcase-leaderboard"><LeaderboardStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Karts" title="Inventory list">
        <div id="coach-showcase-karts-list"><KartsListStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="New Kart" title="Catalogue and custom form">
        <div id="coach-showcase-karts-new"><KartsNewStage /></div>
      </ShowcaseSurface>
      <ShowcaseSurface eyebrow="Kart Detail" title="Inline edit and stats">
        <div id="coach-showcase-kart-detail"><KartDetailStage /></div>
      </ShowcaseSurface>
    </ShowcaseShell>
  );
}
