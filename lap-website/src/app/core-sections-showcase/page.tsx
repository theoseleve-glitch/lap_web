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
  return <span className={`inline-flex rounded border px-2 py-0.5 font-telemetry text-[10px] uppercase tracking-[0.12em] ${className}`}>{label}</span>;
}

function VisualizeListStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Visualization" subtitle="Telemetry playback, analyzer access, and session browsing." />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Sessions" value={148} />
        <StatCard label="Tracks" value={12} />
        <StatCard label="PB Alerts" value={9} trend="up" />
        <StatCard label="Analyzer Ready" value={42} />
      </div>
      <div className="flex gap-3">
        <div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Search sessions, drivers, tracks...</div>
        <div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">Recent first</div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {[
          ['Night stint replay', 'Ethan Rees', 'Spa-Francorchamps', '24 laps', '1:02.441', '92', 'A'],
          ['Qualifying push', 'Mia Duval', 'Barcelona', '8 laps', '1:01.908', '95', 'S'],
        ].map(([title, driver, track, laps, best, score, grade]) => (
          <div key={title} className="rounded-lg border border-steel/20 bg-concrete p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-monument text-lg text-chalk">{title}</p>
                <p className="mt-1 text-sm text-steel">{driver} . {track}</p>
              </div>
              <Chip label="Practice" />
            </div>
            <div className="mt-4 grid grid-cols-4 gap-3">
              <div><span className="block font-telemetry text-[10px] text-steel/60">LAPS</span><span className="text-sm text-chalk">{laps}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">BEST</span><span className="text-sm text-chalk">{best}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">SCORE</span><span className="text-sm text-acid-green">{score}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">GRADE</span><span className="text-sm text-chalk">{grade}</span></div>
            </div>
            <div className="mt-4 flex gap-2">
              <span className="rounded border border-gold/30 bg-gold/10 px-3 py-2 font-telemetry text-xs uppercase text-gold">Analyze</span>
              <span className="rounded border border-steel/30 px-3 py-2 font-telemetry text-xs uppercase text-chalk">Visualize -></span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnalyzerStage() {
  return (
    <div className="rounded-[28px] border border-acid-green/20 bg-[linear-gradient(180deg,rgba(12,18,12,0.92),rgba(8,8,8,0.96))] p-6">
      <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
        <div>
          <p className="font-telemetry text-xs uppercase tracking-wider text-acid-green">Driving Analyzer</p>
          <p className="mt-2 font-monument text-2xl text-chalk">Night stint replay</p>
        </div>
        <div className="flex gap-2">
          <span className="rounded border border-steel/30 px-3 py-2 font-telemetry text-xs uppercase text-chalk">Lap 17</span>
          <span className="rounded border border-gold/30 bg-gold/10 px-3 py-2 font-telemetry text-xs uppercase text-gold">Overlay Lap 03</span>
          <span className="rounded border border-steel/30 px-3 py-2 font-telemetry text-xs uppercase text-steel">Esc</span>
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <Chip label="Telemetry" tone="green" />
        <Chip label="Lines" />
        <Chip label="Inputs" />
        <Chip label="Notes" />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_0.9fr_0.8fr]">
        <Card title="Track Map"><div className="h-64 rounded bg-[radial-gradient(circle_at_30%_30%,rgba(0,212,255,0.18),transparent_35%),linear-gradient(180deg,#101010,#050505)]" /></Card>
        <Card title="Cockpit + Speed Trace"><div className="h-64 rounded bg-[linear-gradient(180deg,#111,#050505)]" /><div className="mt-3 h-20 rounded bg-asphalt" /></Card>
        <Card title="Live Data Rail"><div className="space-y-3 text-sm text-steel"><div className="flex justify-between"><span>Throttle</span><span className="text-chalk">82%</span></div><div className="flex justify-between"><span>Brake</span><span className="text-chalk">12%</span></div><div className="flex justify-between"><span>Steer</span><span className="text-chalk">-8 deg</span></div><div className="flex justify-between"><span>Delta</span><span className="text-acid-green">-0.118</span></div></div></Card>
      </div>
      <div className="mt-4 rounded-lg border border-steel/20 bg-concrete px-4 py-3">
        <div className="flex items-center justify-between"><span className="font-telemetry text-xs uppercase text-steel">Playbar</span><span className="font-telemetry text-xs uppercase text-steel">1x / 2x / 4x</span></div>
        <div className="mt-3 h-2 rounded-full bg-asphalt"><div className="h-full w-[38%] rounded-full bg-acid-green" /></div>
      </div>
    </div>
  );
}

function VisualizeDetailStage() {
  return (
    <div className="rounded-[28px] border border-white/10 bg-black p-6">
      <div className="flex items-center justify-between gap-4 border-b border-white/10 pb-4">
        <div className="flex items-center gap-3">
          <span className="rounded border border-steel/30 px-3 py-2 font-telemetry text-xs uppercase text-chalk">Back to Session</span>
          <div>
            <p className="font-monument text-xl text-chalk">night-stint-17.csv</p>
            <p className="text-sm text-steel">Spa-Francorchamps . Best 1:02.441</p>
          </div>
        </div>
        <span className="rounded border border-gold/30 bg-gold/10 px-3 py-2 font-telemetry text-xs uppercase text-gold">Compare Lap On</span>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title="2.5D Track Map"><div className="h-72 rounded bg-[radial-gradient(circle_at_40%_30%,rgba(0,212,255,0.14),transparent_35%),linear-gradient(180deg,#111,#050505)]" /></Card>
        <Card title="Speed Trace + Delta"><div className="h-72 rounded bg-asphalt" /></Card>
        <Card title="G-G Explorer"><div className="h-72 rounded bg-asphalt" /></Card>
      </div>
      <div className="mt-4 rounded-lg border border-steel/20 bg-concrete px-4 py-3">
        <div className="flex items-center justify-between"><span className="font-telemetry text-xs uppercase text-steel">Bottom Lap Bar</span><span className="font-telemetry text-xs uppercase text-steel">Hide / Show Laps</span></div>
        <div className="mt-3 flex gap-2"><Chip label="Lap 17" tone="green" /><Chip label="Lap 03" tone="gold" /><Chip label="Lap 21" /></div>
      </div>
    </div>
  );
}

function DriversListStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Drivers" subtitle="Profiles, level progression, and performance summaries." />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Drivers" value={38} />
        <StatCard label="Active" value={29} />
        <StatCard label="Level Ups" value={12} trend="up" />
        <StatCard label="PBs" value={16} />
      </div>
      <div className="flex gap-3">
        <div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Search drivers...</div>
        <div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">Sort: Score</div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {['Mia Duval', 'Noah Vale'].map((driver, index) => (
          <div key={driver} className="rounded-lg border border-steel/20 bg-concrete p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-monument text-lg text-chalk">{driver}</p>
                <p className="mt-1 text-sm text-steel">{index === 0 ? 'Precision' : 'Aggressive'} style</p>
              </div>
              <Chip label={index === 0 ? 'Level 9' : 'Level 11'} tone="gold" />
            </div>
            <div className="mt-4 grid grid-cols-4 gap-3">
              <div><span className="block font-telemetry text-[10px] text-steel/60">SESSIONS</span><span className="text-sm text-chalk">{index === 0 ? 42 : 58}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">LAPS</span><span className="text-sm text-chalk">{index === 0 ? 860 : 1042}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">PB</span><span className="text-sm text-acid-green">1:01.{index === 0 ? '908' : '772'}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">AVG</span><span className="text-sm text-chalk">{index === 0 ? 93 : 91}</span></div>
            </div>
            <div className="mt-4 h-2 rounded-full bg-asphalt"><div className={`h-full rounded-full ${index === 0 ? 'w-[62%]' : 'w-[78%]'} bg-acid-green`} /></div>
            <div className="mt-4 flex items-center justify-between"><span className="rounded border border-steel/30 px-3 py-2 font-telemetry text-xs uppercase text-chalk">Profile -></span><span className="font-telemetry text-xs uppercase text-safety-red/70">Delete</span></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DriverDetailStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Mia Duval" subtitle="Editable profile, progression, style, sessions, and gamification." actions={<Chip label="Precision" tone="gold" />} />
      <div className="grid gap-4 md:grid-cols-[1.2fr_0.8fr]">
        <Card title="Profile Header"><div className="space-y-3"><Field label="Display Name" value="Mia Duval" /><Field label="Notes" value="Strong on low-fuel qualifying and mixed-traffic exits." /><div className="flex gap-2"><Chip label="Level 9" tone="gold" /><Chip label="5-day streak" tone="green" /><Chip label="Licence A" /></div></div></Card>
        <Card title="Licence + XP"><div className="h-28 rounded bg-asphalt" /><div className="mt-3 h-2 rounded-full bg-asphalt"><div className="h-full w-[68%] rounded-full bg-acid-green" /></div></Card>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Sessions" value={42} />
        <StatCard label="PBs" value={7} />
        <StatCard label="Avg Score" value={93} />
        <StatCard label="Records Held" value={3} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]">
        <Card title="Progression Charts"><div className="h-56 rounded bg-asphalt" /></Card>
        <Card title="Style Radar + History"><div className="h-56 rounded bg-asphalt" /></Card>
        <Card title="Achievements"><div className="grid grid-cols-2 gap-2"><div className="h-20 rounded bg-asphalt" /><div className="h-20 rounded bg-asphalt" /><div className="h-20 rounded bg-asphalt" /><div className="h-20 rounded border border-steel/20 bg-black/30 text-center text-sm text-steel">???</div></div></Card>
      </div>
      <TableCard title="Sessions Table"><table className="w-full"><thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Date</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Track</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">PB</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Score</th></tr></thead><tbody><tr className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk">12 Mar</td><td className="px-4 py-3 text-sm text-chalk">Spa</td><td className="px-4 py-3 text-sm text-acid-green">1:01.908</td><td className="px-4 py-3 text-sm text-chalk">95</td></tr></tbody></table></TableCard>
      <div className="rounded-lg border border-safety-red/25 bg-safety-red/5 px-4 py-3 text-sm text-steel">Danger zone confirm state can show cascade impact counts before delete.</div>
    </div>
  );
}

function TracksListStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Tracks" subtitle="Auto-detected tracks, metadata, and evolution views." />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Tracks" value={12} />
        <StatCard label="Sessions" value={148} />
        <StatCard label="GPS Ready" value={9} />
        <StatCard label="Best Avg" value="1:02.1" />
      </div>
      <div className="flex gap-3"><div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Search tracks...</div><div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">Sort: Sessions</div></div>
      <div className="grid gap-4 lg:grid-cols-2">
        {['Spa-Francorchamps', 'Barcelona'].map((track, index) => <div key={track} className="rounded-lg border border-steel/20 bg-concrete p-5"><div className="flex items-start justify-between gap-3"><div><p className="font-monument text-lg text-chalk">{track}</p><p className="mt-1 text-sm text-steel">{index === 0 ? 'GPS + lap count available' : 'Auto-detected from uploads'}</p></div><Chip label={`${index === 0 ? 38 : 24} sessions`} tone="gold" /></div><div className="mt-4 grid grid-cols-3 gap-3"><div><span className="block font-telemetry text-[10px] text-steel/60">LAPS</span><span className="text-sm text-chalk">{index === 0 ? 1280 : 744}</span></div><div><span className="block font-telemetry text-[10px] text-steel/60">GPS</span><span className="text-sm text-chalk">{index === 0 ? 'Yes' : 'No'}</span></div><div><span className="block font-telemetry text-[10px] text-steel/60">ACTION</span><span className="text-sm text-acid-green">Open -></span></div></div></div>)}
      </div>
    </div>
  );
}

function TrackDetailStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Spa-Francorchamps" subtitle="Metadata, impact-aware delete flow, and inline editing." actions={<div className="flex gap-2"><Chip label="Evolution" tone="green" /><Chip label="Edit" /><Chip label="Delete" tone="red" /></div>} />
      <div className="rounded-lg border border-safety-red/25 bg-safety-red/5 px-4 py-3 text-sm text-steel">Delete impact panel: 38 sessions linked, 4 weekend references, 1 record cascade.</div>
      <div className="grid gap-4 md:grid-cols-2"><Card title="Inline Edit Form"><div className="grid gap-4 md:grid-cols-2"><Field label="Track Name" value="Spa-Francorchamps" /><Field label="Country" value="Belgium" /><Field label="Layout" value="GP" /><Field label="Surface" value="Dry + wet notes" /></div></Card><Card title="Stats"><div className="grid grid-cols-2 gap-4"><StatCard label="Sessions" value={38} /><StatCard label="Drivers" value={24} /><StatCard label="PB" value="1:01.772" /><StatCard label="GPS Laps" value={1280} /></div></Card></div>
      <TableCard title="Track Information"><table className="w-full"><tbody><tr className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-steel">Detected from</td><td className="px-4 py-3 text-sm text-chalk">Uploaded session data</td></tr><tr className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-steel">Records held</td><td className="px-4 py-3 text-sm text-chalk">3</td></tr><tr><td className="px-4 py-3 text-sm text-steel">Notes</td><td className="px-4 py-3 text-sm text-chalk">High commitment sector 2 and strong elevation change.</td></tr></tbody></table></TableCard>
    </div>
  );
}

function TrackEvolutionStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Track Evolution" subtitle="Trend tables, sector splits, corner performance, and conditions." />
      <div className="flex gap-2"><Chip label="Dry" tone="green" /><Chip label="Mixed" tone="gold" /><Chip label="Wet" /></div>
      <TableCard title="Lap-Time Trend"><table className="w-full"><thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Window</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Avg Lap</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Delta</th></tr></thead><tbody><tr className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk">Morning</td><td className="px-4 py-3 text-sm text-chalk">1:03.220</td><td className="px-4 py-3 text-sm text-acid-green">-0.412</td></tr><tr><td className="px-4 py-3 text-sm text-chalk">Night</td><td className="px-4 py-3 text-sm text-chalk">1:03.774</td><td className="px-4 py-3 text-sm text-safety-red">+0.142</td></tr></tbody></table></TableCard>
      <div className="grid gap-4 xl:grid-cols-2"><TableCard title="Sector Breakdown"><table className="w-full"><thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Sector</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Best</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Spread</th></tr></thead><tbody><tr className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk">S1</td><td className="px-4 py-3 text-sm text-chalk">18.441</td><td className="px-4 py-3 text-sm text-chalk">0.32</td></tr><tr><td className="px-4 py-3 text-sm text-chalk">S2</td><td className="px-4 py-3 text-sm text-chalk">21.003</td><td className="px-4 py-3 text-sm text-chalk">0.48</td></tr></tbody></table></TableCard><Card title="Corner Performance"><div className="space-y-3">{['La Source','Pouhon','Bus Stop'].map((corner, index) => <div key={corner}><div className="flex justify-between text-sm"><span className="text-steel">{corner}</span><span className="text-chalk">{92 - index * 4}%</span></div><div className="mt-1 h-2 rounded-full bg-asphalt"><div className={`h-full rounded-full ${index === 0 ? 'w-[92%]' : index === 1 ? 'w-[88%]' : 'w-[84%]'} bg-acid-green`} /></div></div>)}</div></Card></div>
    </div>
  );
}

function WeekendsListStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Weekends" subtitle="Weekend planning, session grouping, and summary cards." actions={<span className="rounded bg-gold px-4 py-2 font-telemetry text-sm text-white">+ New Weekend</span>} />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4"><StatCard label="Weekends" value={12} /><StatCard label="Past" value={9} /><StatCard label="Upcoming" value={3} /><StatCard label="Unique Tracks" value={7} /></div>
      <div className="flex gap-3"><div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Search weekends...</div><div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">Sort: Date</div></div>
      <div className="grid gap-4 lg:grid-cols-2">
        {['Spa Sprint Camp', 'Barcelona Prep'].map((weekend, index) => <div key={weekend} className="rounded-lg border border-steel/20 bg-concrete p-5"><div className="flex items-start justify-between gap-3"><div><p className="font-monument text-lg text-chalk">{weekend}</p><p className="mt-1 text-sm text-steel">{index === 0 ? '14-16 Mar 2025' : '28-30 Mar 2025'}</p></div><Chip label={index === 0 ? 'PAST' : 'UPCOMING'} tone={index === 0 ? 'default' : 'gold'} /></div><div className="mt-4 grid grid-cols-3 gap-3"><div><span className="block font-telemetry text-[10px] text-steel/60">SESSIONS</span><span className="text-sm text-chalk">{index === 0 ? 5 : 3}</span></div><div><span className="block font-telemetry text-[10px] text-steel/60">TRACK</span><span className="text-sm text-chalk">{index === 0 ? 'Spa' : 'Barcelona'}</span></div><div><span className="block font-telemetry text-[10px] text-steel/60">NOTES</span><span className="text-sm text-chalk">{index === 0 ? 'Yes' : 'No'}</span></div></div></div>)}
      </div>
    </div>
  );
}

function WeekendNewStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="New Weekend" subtitle="Compact creation flow with notes and date bounds." />
      <Card title="Weekend Form"><div className="grid gap-4 md:grid-cols-2"><Field label="Weekend Name" value="Spa Sprint Camp" /><Field label="Track" value="Spa-Francorchamps" /><Field label="Start Date" value="2025-03-14" /><Field label="End Date" value="2025-03-16" /><div className="md:col-span-2"><Field label="Notes" value="Focus on qualifying trim, fuel management, and race-start drills." /></div></div><div className="mt-4 flex gap-2"><span className="rounded bg-gold px-4 py-2 font-telemetry text-xs uppercase text-white">Create Weekend</span><span className="rounded border border-steel/30 px-4 py-2 font-telemetry text-xs uppercase text-steel">Cancel</span></div></Card>
    </div>
  );
}

function WeekendDetailStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Spa Sprint Camp" subtitle="Weekend summary, session progression, and comparison tables." actions={<div className="flex gap-2"><Chip label="Add Sessions" tone="green" /><Chip label="Delete" tone="red" /></div>} />
      <div className="rounded-lg border border-steel/20 bg-concrete px-4 py-3 text-sm text-steel">Add-sessions panel open: choose existing sessions, reorder rows, and expand one row for drilldown.</div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4"><StatCard label="Sessions" value={5} /><StatCard label="PB Gain" value="-0.412" /><StatCard label="Avg Score" value={91} /><StatCard label="Time Delta" value="-1.22" /></div>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr_0.9fr]"><Card title="Progression Chart"><div className="h-56 rounded bg-asphalt" /></Card><Card title="Lap-Time Trend"><div className="h-56 rounded bg-asphalt" /></Card><Card title="Notes + Score Split"><div className="space-y-3 text-sm text-steel"><p>Focus weekend with repeat sessions under similar weather conditions.</p><div className="h-2 rounded-full bg-asphalt"><div className="h-full w-[74%] rounded-full bg-acid-green" /></div><div className="h-2 rounded-full bg-asphalt"><div className="h-full w-[61%] rounded-full bg-gold" /></div></div></Card></div>
      <TableCard title="Sessions List"><table className="w-full"><thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Session</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Track</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Score</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Row</th></tr></thead><tbody><tr className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk">Qualifying Run</td><td className="px-4 py-3 text-sm text-chalk">Spa</td><td className="px-4 py-3 text-sm text-chalk">95</td><td className="px-4 py-3 text-sm text-acid-green">Expanded</td></tr></tbody></table></TableCard>
      <div className="grid gap-4 xl:grid-cols-2"><TableCard title="Pillar Comparison"><table className="w-full"><thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Pillar</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Delta</th></tr></thead><tbody><tr className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk">Braking</td><td className="px-4 py-3 text-sm text-acid-green">+6</td></tr><tr><td className="px-4 py-3 text-sm text-chalk">Traction</td><td className="px-4 py-3 text-sm text-gold">+2</td></tr></tbody></table></TableCard><Card title="Grade Distribution"><div className="grid grid-cols-4 gap-2"><div className="h-24 rounded bg-asphalt" /><div className="h-24 rounded bg-asphalt" /><div className="h-24 rounded bg-asphalt" /><div className="h-24 rounded bg-asphalt" /></div></Card></div>
    </div>
  );
}

export default function CoreSectionsShowcasePage() {
  return (
    <ShowcaseShell eyebrow="Core Sections" title="Visualization, drivers, tracks, and weekends" description="Capture page for the next batch of core product sections beyond strategy, reports, navigation, and gamification." links={[{ href: '/strategy-showcase', label: 'Strategy' }, { href: '/reports-showcase', label: 'Reports' }, { href: '/navigation-showcase', label: 'Navigation' }]}>
      <ShowcaseSurface eyebrow="Visualization" title="List workspace"><div id="core-showcase-visualize-list"><VisualizeListStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Analyzer" title="DrivingAnalyzer modal"><div id="core-showcase-analyzer"><AnalyzerStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Visualization Detail" title="Full-screen telemetry workspace"><div id="core-showcase-visualize-detail"><VisualizeDetailStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Drivers" title="Driver list"><div id="core-showcase-drivers-list"><DriversListStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Driver Detail" title="Profile, progression, and achievements"><div id="core-showcase-driver-detail"><DriverDetailStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Tracks" title="Tracks list"><div id="core-showcase-tracks-list"><TracksListStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Track Detail" title="Metadata and inline edit"><div id="core-showcase-track-detail"><TrackDetailStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Track Evolution" title="Trend tables and corner performance"><div id="core-showcase-track-evolution"><TrackEvolutionStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Weekends" title="Weekend list"><div id="core-showcase-weekends-list"><WeekendsListStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="New Weekend" title="Creation form"><div id="core-showcase-weekend-new"><WeekendNewStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Weekend Detail" title="Summary, sessions, and comparisons"><div id="core-showcase-weekend-detail"><WeekendDetailStage /></div></ShowcaseSurface>
    </ShowcaseShell>
  );
}
