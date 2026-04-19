import type { ReactNode } from 'react';
import { StatCard } from '@/components/app/StatCard';
import { MessageLog } from '@/components/app/race-strategy/MessageLog';
import { StintTimeline } from '@/components/app/race-strategy/StintTimeline';
import { ShowcaseShell, ShowcaseSurface } from '@/components/showcase/ShowcaseShell';
import { PageIntro } from '@/components/ui/PageIntro';

type StrategyStint = {
  stint_id: number;
  stint_order: number;
  driver_id: number;
  driver_name: string;
  planned_duration_s: number | null;
  actual_duration_s: number | null;
  status: string;
};

const driverColors = { 12: '#b6ff2e', 27: '#00d4ff', 33: '#ff8a3d', 44: '#f2c94c' };

const drivers = [
  { id: 12, order: 1, name: 'Noah Vale', weight: '74.0 kg', com: 'CH1', min: '50:00', max: '1:08:00' },
  { id: 27, order: 2, name: 'Mia Duval', weight: '66.5 kg', com: 'CH2', min: '48:00', max: '1:05:00' },
  { id: 33, order: 3, name: 'Ethan Rees', weight: '81.2 kg', com: 'CH3', min: '52:00', max: '1:10:00' },
  { id: 44, order: 4, name: 'Lina Hart', weight: '59.7 kg', com: 'CH4', min: '46:00', max: '1:02:00' },
];

const stints: StrategyStint[] = [
  { stint_id: 1, stint_order: 1, driver_id: 12, driver_name: 'Noah Vale', planned_duration_s: 3900, actual_duration_s: 3840, status: 'completed' },
  { stint_id: 2, stint_order: 2, driver_id: 27, driver_name: 'Mia Duval', planned_duration_s: 4080, actual_duration_s: 4140, status: 'completed' },
  { stint_id: 3, stint_order: 3, driver_id: 33, driver_name: 'Ethan Rees', planned_duration_s: 4020, actual_duration_s: 3960, status: 'completed' },
  { stint_id: 4, stint_order: 4, driver_id: 44, driver_name: 'Lina Hart', planned_duration_s: 3840, actual_duration_s: 3840, status: 'live' },
  { stint_id: 5, stint_order: 5, driver_id: 12, driver_name: 'Noah Vale', planned_duration_s: 3780, actual_duration_s: null, status: 'planned' },
];

const totalPlanned = stints.reduce((sum, stint) => sum + (stint.planned_duration_s ?? stint.actual_duration_s ?? 0), 0);
const totalActual = stints.reduce((sum, stint) => sum + (stint.actual_duration_s ?? stint.planned_duration_s ?? 0), 0);

const messages = [
  { msg_id: 1, author: 'Engineer', message: 'Traffic cluster in sector 2. Hold the overcut.', category: 'strategy', created_at: '2025-03-12T01:44:00Z' },
  { msg_id: 2, author: 'Pit Wall', message: 'Penalty window active. Passage minimum 150s.', category: 'incident', created_at: '2025-03-12T01:47:00Z' },
  { msg_id: 3, author: 'Race Control', message: 'Fuel margin stable. Re-optimization complete.', category: 'info', created_at: '2025-03-12T01:50:00Z' },
];

function tone(status: string) {
  if (status === 'live') return 'border-acid-green/30 bg-acid-green/10 text-acid-green';
  if (status === 'ready') return 'border-gold/30 bg-gold/10 text-gold';
  if (status === 'finished') return 'border-chalk/20 bg-white/5 text-chalk';
  return 'border-steel/30 bg-steel/10 text-steel';
}

function buttonTone(kind: 'gold' | 'green' | 'danger' | 'ghost') {
  if (kind === 'gold') return 'border border-gold bg-gold text-white hover:bg-gold/80';
  if (kind === 'green') return 'border border-acid-green bg-acid-green text-asphalt hover:bg-acid-green/80';
  if (kind === 'danger') return 'border border-safety-red/40 text-safety-red hover:bg-safety-red/10';
  return 'border border-steel/30 text-chalk hover:bg-concrete';
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null) return '--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}` : `${m}:${s.toString().padStart(2, '0')}`;
}

function StatusPill({ label, className }: { label: string; className: string }) {
  return <span className={`inline-flex items-center rounded border px-2 py-0.5 font-telemetry text-[10px] uppercase tracking-[0.12em] ${className}`}>{label}</span>;
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

function DetailCard({ title, rows }: { title: string; rows: Array<[string, string]> }) {
  return (
    <div className="rounded-lg border border-steel/20 bg-concrete p-4">
      <h3 className="font-telemetry text-xs uppercase tracking-wider text-steel">{title}</h3>
      <div className="mt-3 space-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4">
            <span className="text-steel">{label}</span>
            <span className="text-chalk">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StaticField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="mb-1 font-telemetry text-[11px] uppercase tracking-[0.08em] text-steel">{label}</p>
      <div className="rounded border border-steel/30 bg-asphalt px-3 py-2 text-sm text-chalk">{value}</div>
    </div>
  );
}

function StaticCheckbox({ label, checked }: { label: string; checked: boolean }) {
  return (
    <div className="flex items-center gap-2 text-sm text-steel">
      <span className={`flex h-4 w-4 items-center justify-center rounded border ${checked ? 'border-pit-orange bg-pit-orange/15 text-pit-orange' : 'border-steel/30 text-transparent'}`}>x</span>
      {label}
    </div>
  );
}

function SectionPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border border-steel/20 bg-concrete p-5">
      <h2 className="mb-4 font-monument text-lg text-chalk">{title}</h2>
      {children}
    </div>
  );
}

function ListStage() {
  const cards = [
    { name: '24H Spa - Pro Class', track: 'Spa-Francorchamps', team: 'North Star Motorsport', duration: '24:00:00', stints: 18, created: '12 Mar 2025', action: 'Race Control ->', status: 'live', confirmDelete: false },
    { name: 'Silverstone 6H', track: 'Silverstone GP', team: 'Telemetry Works', duration: '6:00:00', stints: 5, created: '08 Mar 2025', action: 'Configure ->', status: 'ready', confirmDelete: true },
    { name: 'Paul Ricard Night Test', track: 'Paul Ricard', team: 'Night Shift Racing', duration: '3:00:00', stints: 3, created: '05 Mar 2025', action: 'Configure ->', status: 'draft', confirmDelete: false },
    { name: 'Barcelona 12H Retro', track: 'Barcelona', team: 'Apex Telemetry', duration: '12:00:00', stints: 10, created: '02 Mar 2025', action: 'Summary ->', status: 'finished', confirmDelete: false },
  ];

  return (
    <div className="space-y-6">
      <PageIntro
        title="Race Strategy"
        subtitle="Endurance race management - plan, optimize, and run"
        actions={<button type="button" className="rounded bg-gold px-4 py-2 font-telemetry text-sm text-white">+ New Race <span className="ml-1 text-[10px] opacity-60">4h max</span></button>}
      />

      <details open className="rounded-lg border border-steel/20 bg-concrete">
        <summary className="cursor-pointer px-5 py-3 font-telemetry text-xs uppercase tracking-[0.08em] text-steel">How Race Strategy works</summary>
        <div className="grid grid-cols-1 gap-4 px-5 pb-4 text-sm sm:grid-cols-4">
          <p className="text-steel"><span className="block font-telemetry text-[10px] text-steel/60">1. CREATE</span>Set track, duration, lineup, and target stints.</p>
          <p className="text-steel"><span className="block font-telemetry text-[10px] text-gold">2. PLAN</span>Assign stints, fuel windows, and timeline logic.</p>
          <p className="text-steel"><span className="block font-telemetry text-[10px] text-acid-green">3. GO LIVE</span>Track lap times and pit decisions in real time.</p>
          <p className="text-steel"><span className="block font-telemetry text-[10px] text-chalk">4. REVIEW</span>Inspect summaries, deltas, and race outcomes.</p>
        </div>
      </details>

      <div className="rounded-lg border border-gold/25 bg-gold/10 px-4 py-3 text-sm text-steel">
        <p className="font-telemetry text-xs uppercase tracking-wider text-gold">Upgrade Required</p>
        <p className="mt-1">Demo plan: races up to 4 hours. Upgrade for 24-hour races and advanced features.</p>
      </div>

      <div className="flex items-center justify-between rounded-lg border border-safety-red/30 bg-safety-red/10 px-4 py-3 text-sm text-safety-red">
        <span>Delete failed: live races cannot be removed while timing is active.</span>
        <span className="font-telemetry text-xs uppercase text-safety-red/60">dismiss</span>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Total Races" value={12} />
        <StatCard label="Live Now" value={2} trend="up" />
        <StatCard label="Completed" value={34} />
        <StatCard label="Race Hours" value="164.0" unit="h" />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="flex-1 rounded border border-steel/30 bg-concrete px-4 py-2.5 text-sm text-steel">Search races, tracks, teams...</div>
        <div className="rounded border border-steel/30 bg-concrete px-3 py-2.5 text-sm text-chalk">All Status</div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {cards.map((card) => (
          <div key={card.name} className={`rounded-lg border bg-concrete p-5 ${card.status === 'live' ? 'border-acid-green/30' : 'border-steel/20'}`}>
            <div className="flex items-start justify-between gap-3">
              <h3 className="font-monument text-lg text-chalk">{card.name}</h3>
              <div className="flex items-center gap-2">
                <StatusPill label={card.status} className={tone(card.status)} />
                {card.confirmDelete ? (
                  <span className="inline-flex items-center gap-1">
                    <span className="rounded border border-safety-red/40 bg-safety-red/20 px-2 py-0.5 font-telemetry text-[10px] uppercase text-safety-red">Confirm</span>
                    <span className="font-telemetry text-[10px] uppercase text-steel">Cancel</span>
                  </span>
                ) : null}
              </div>
            </div>
            <div className="mt-1 flex items-center gap-3 text-sm text-steel">
              <span>{card.track}</span>
              <span className="text-steel/60">.</span>
              <span>{card.team}</span>
            </div>
            <div className="mt-4 grid grid-cols-4 gap-3">
              <div><span className="block font-telemetry text-[10px] text-steel/60">DURATION</span><span className="font-telemetry text-sm text-chalk">{card.duration}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">STINTS</span><span className="font-telemetry text-sm text-chalk">{card.stints}</span></div>
              <div><span className="block font-telemetry text-[10px] text-steel/60">CREATED</span><span className="font-telemetry text-xs text-steel">{card.created}</span></div>
              <div className="text-right"><span className="block font-telemetry text-[10px] text-steel/60">ACTION</span><span className="font-telemetry text-xs text-acid-green/70">{card.action}</span></div>
            </div>
            {card.status === 'live' ? <div className="mt-3 h-0.5 overflow-hidden rounded-full bg-acid-green/25"><div className="h-full w-1/3 rounded-full bg-acid-green animate-pulse" /></div> : null}
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-steel/20 bg-concrete p-5 text-center">
          <p className="font-telemetry text-xs uppercase tracking-wider text-steel">Filtered Empty State</p>
          <p className="mt-3 text-sm text-steel">No races match your filters.</p>
          <span className="mt-3 inline-flex rounded border border-gold/40 px-3 py-1 font-telemetry text-xs uppercase text-gold">Clear filters</span>
        </div>
        <div className="rounded-lg border border-steel/20 bg-concrete p-5 text-center">
          <p className="font-telemetry text-xs uppercase tracking-wider text-steel">First-Use Empty State</p>
          <h4 className="mt-3 font-monument text-lg text-chalk">No races yet</h4>
          <p className="mx-auto mt-2 max-w-sm text-sm text-steel">Create your first endurance race strategy. Plan pit stops, manage driver stints, and optimize for the win.</p>
        </div>
      </div>
    </div>
  );
}

function ConfigStage() {
  const summary = {
    race: [['Duration', '24:00:00'], ['Stints', '18'], ['Min Pit Stop', '1:00']] as Array<[string, string]>,
    weight: [['Empty Kart', '162 kg'], ['Full Tank', '184 kg'], ['Min Total', '240 kg']] as Array<[string, string]>,
    fuel: [['Autonomy', '1:05:00']] as Array<[string, string]>,
  };

  return (
    <div className="space-y-6">
      <PageIntro eyebrow="< All Races" title="24H Spa - Pro Class" subtitle="Spa-Francorchamps - North Star Motorsport" actions={<StatusPill label="READY" className={tone('ready')} />} />

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('gold')}`}>Optimize</button>
        <div className="rounded-lg border border-gold/30 bg-gold/10 px-4 py-2 text-sm text-chalk">
          <p>Start the race? Timer will begin.</p>
          <div className="mt-2 flex gap-2"><span className="rounded bg-gold px-3 py-1 font-telemetry text-xs uppercase text-white">Confirm</span><span className="rounded border border-steel/30 px-3 py-1 font-telemetry text-xs uppercase text-steel">Cancel</span></div>
        </div>
        <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('ghost')}`}>Edit</button>
        <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('danger')}`}>Delete</button>
      </div>

      <div className="flex items-center justify-between rounded-lg border border-safety-red/30 bg-safety-red/10 px-4 py-2">
        <p className="font-telemetry text-xs text-safety-red">Action failed: fuel autonomy missing for two planned stints.</p>
        <span className="text-xs text-safety-red/60">dismiss</span>
      </div>

      <div className="rounded-lg border border-safety-red/25 bg-safety-red/5 px-4 py-3 text-sm text-steel">Delete confirmation removes planned stints, pit windows, and live race state.</div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <DetailCard title="Race" rows={summary.race} />
        <DetailCard title="Weight" rows={summary.weight} />
        <DetailCard title="Fuel" rows={summary.fuel} />
      </div>

      <TableCard title="Drivers">
        <table className="w-full">
          <thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">#</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Weight</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">COM</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Min Stint</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Max Stint</th></tr></thead>
          <tbody>{drivers.map((driver) => <tr key={driver.id} className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk">{driver.order}</td><td className="px-4 py-3 text-sm text-chalk"><div className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ backgroundColor: driverColors[driver.id as keyof typeof driverColors] }} />{driver.name}</div></td><td className="px-4 py-3 text-sm text-chalk">{driver.weight}</td><td className="px-4 py-3 text-sm text-chalk">{driver.com}</td><td className="px-4 py-3 text-sm text-chalk">{driver.min}</td><td className="px-4 py-3 text-sm text-chalk">{driver.max}</td></tr>)}</tbody>
        </table>
      </TableCard>

      <div className="space-y-2">
        <h3 className="font-telemetry text-xs uppercase tracking-wider text-steel">Stint Timeline</h3>
        <StintTimeline stints={stints} totalDuration={totalPlanned} driverColors={driverColors} />
      </div>

      <TableCard title="Stints">
        <table className="w-full min-w-[1080px]">
          <thead><tr className="border-b border-steel/20"><th className="px-2 py-3 font-telemetry text-xs uppercase tracking-wider text-steel">Order</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">#</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Start</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">End</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Duration</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Fuel Start</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Fuel End</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Ballast</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Laps</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Pit Lap</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Status</th></tr></thead>
          <tbody>{stints.map((stint, index) => <tr key={stint.stint_id} className="border-b border-steel/10"><td className="px-2 py-3 text-center font-telemetry text-xs text-steel">^<br />v</td><td className="px-4 py-3 text-sm text-chalk">{stint.stint_order}</td><td className="px-4 py-3 text-sm text-chalk"><span className="rounded border border-steel/20 bg-asphalt px-2 py-1">{stint.driver_name}</span></td><td className="px-4 py-3 text-sm text-chalk">{formatDuration(index * 3960)}</td><td className="px-4 py-3 text-sm text-chalk">{formatDuration((index + 1) * 3960)}</td><td className="px-4 py-3 text-sm text-chalk">{formatDuration(stint.planned_duration_s)}</td><td className="px-4 py-3 text-sm text-chalk">{(32 - index * 4).toFixed(1)} kg</td><td className="px-4 py-3 text-sm text-chalk">{(25 - index * 4).toFixed(1)} kg</td><td className="px-4 py-3 text-sm text-chalk">{index % 2 === 0 ? '12 kg' : '6 kg'}</td><td className="px-4 py-3 text-sm text-chalk">{32 - index}</td><td className="px-4 py-3 text-sm text-chalk">{31 - index}</td><td className="px-4 py-3"><StatusPill label={stint.status} className={tone(stint.status)} /></td></tr>)}</tbody>
        </table>
      </TableCard>
    </div>
  );
}

function BuilderStage() {
  return (
    <div className="space-y-6">
      <PageIntro title="Race Setup Builder" subtitle="Create and edit the advanced strategy form with driver rules, pit logic, weather windows, and endurance-only planning blocks." actions={<StatusPill label="24H COMPLEX" className="border-gold/30 bg-gold/10 text-gold" />} />

      <div className="rounded-lg border border-safety-red/30 bg-safety-red/10 px-4 py-3 text-sm text-safety-red">Validation error: each named driver needs a COM channel and an average lap time before optimization.</div>
      <div className="rounded-lg border border-gold/25 bg-gold/10 px-4 py-3 text-sm text-steel">Racer plan: races up to 24 hours. Upgrade to World-Class for unlimited duration.</div>

      <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        <div className="space-y-4">
          <SectionPanel title="Race Details">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <StaticField label="Race Name" value="24H Spa - Pro Class" />
              <StaticField label="Team Name" value="North Star Motorsport" />
              <StaticField label="Track" value="Spa-Francorchamps" />
              <div className="grid grid-cols-3 gap-2">
                <StaticField label="Duration (h)" value="24" />
                <StaticField label="Minutes" value="0" />
                <StaticField label="Stints" value="18" />
              </div>
            </div>
          </SectionPanel>

          <SectionPanel title="Drivers">
            <div className="mb-4 flex items-center justify-between"><p className="text-sm text-steel">Enter at least one driver name to build the strategy.</p><span className="border border-pit-orange/40 px-3 py-1 font-telemetry text-sm text-pit-orange">+ Add Driver</span></div>
            <div className="mb-4 border border-steel/10 bg-asphalt/30 p-3">
              <p className="font-telemetry text-xs uppercase tracking-wider text-steel">v Default Driver Rules</p>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                <StaticField label="Min Stint" value="48:00" />
                <StaticField label="Max Stint" value="1:08:00" />
                <StaticField label="Min Total" value="2:00:00" />
                <StaticField label="Max Total" value="6:15:00" />
                <StaticField label="Min Rest" value="1:30:00" />
                <div className="flex items-end"><StaticCheckbox label="Allow double stint" checked /></div>
              </div>
              <span className="mt-3 inline-flex border border-gold/40 px-3 py-1.5 font-telemetry text-xs uppercase text-gold">Apply to all drivers</span>
            </div>
            <div className="space-y-3">
              {drivers.slice(0, 3).map((driver, index) => (
                <div key={driver.id} className="border border-steel/10 bg-asphalt/40 p-3">
                  <div className="mb-2 flex items-center gap-3"><span className="h-8 w-8 rounded border border-white/10" style={{ backgroundColor: driverColors[driver.id as keyof typeof driverColors] }} /><div className="flex-1 rounded border border-steel/30 bg-asphalt px-3 py-2 text-sm text-chalk">{driver.name}</div><div className="w-20 rounded border border-steel/30 bg-asphalt px-3 py-2 text-sm text-chalk">{driver.weight.replace(' kg', '')}</div><span className="font-telemetry text-xs uppercase text-steel">{index === 0 ? 'v Rules' : '> Rules'}</span></div>
                  <div className="grid grid-cols-1 gap-3 pl-11 md:grid-cols-2"><StaticField label="COM Channel" value={driver.com} /><StaticField label="Avg Lap Time (s)" value={index === 0 ? '62.5' : index === 1 ? '63.1' : '62.8'} /></div>
                </div>
              ))}
            </div>
          </SectionPanel>

          <SectionPanel title="Pit Strategy">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3"><StaticField label="Min Pit Stop (s)" value="60" /></div>
            <div className="mt-4 flex flex-wrap gap-6"><StaticCheckbox label="Mandatory driver change" checked /><StaticCheckbox label="Refueling allowed" checked /><StaticCheckbox label="Quick change (Sport category)" checked /></div>
            <div className="mt-4">
              <p className="mb-2 font-telemetry text-[11px] uppercase tracking-[0.08em] text-steel">Optimization Mode</p>
              <div className="flex gap-2"><span className="border border-steel/30 px-4 py-2 font-telemetry text-sm uppercase text-steel">Equal Time</span><span className="border border-pit-orange bg-pit-orange px-4 py-2 font-telemetry text-sm uppercase text-white">Performance</span></div>
            </div>
          </SectionPanel>
        </div>

        <div className="space-y-4">
          <SectionPanel title="Tech Stop">
            <StaticCheckbox label="Enable mandatory tech stop" checked />
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3"><StaticField label="Duration (mm:ss)" value="5:00" /><StaticField label="Window Start" value="08:00" /><StaticField label="Window End" value="16:00" /></div>
          </SectionPanel>
          <SectionPanel title="Weather Forecast">
            <div className="grid grid-cols-4 gap-2"><StaticField label="Start" value="00:00" /><StaticField label="End" value="06:00" /><StaticField label="Condition" value="Dry" /><StaticField label="Confidence" value="90%" /></div>
            <div className="mt-3 grid grid-cols-4 gap-2"><StaticField label="Start" value="06:00" /><StaticField label="End" value="10:00" /><StaticField label="Condition" value="Light Rain" /><StaticField label="Confidence" value="65%" /></div>
          </SectionPanel>
          <SectionPanel title="Sleep Windows">
            <div className="grid grid-cols-4 gap-2"><StaticField label="Driver" value="Lina Hart" /><StaticField label="Start" value="01:00" /><StaticField label="End" value="03:30" /><StaticField label="Label" value="Core rest" /></div>
          </SectionPanel>
          <SectionPanel title="Fuel & Weight">
            <div className="grid grid-cols-2 gap-4"><StaticField label="Fuel Autonomy" value="1:05:00" /><StaticField label="Empty Kart" value="162 kg" /><StaticField label="Full Tank" value="184 kg" /><StaticField label="Min Total" value="240 kg" /></div>
          </SectionPanel>
          <SectionPanel title="Qualifying">
            <div className="grid grid-cols-2 gap-4"><StaticField label="Duration" value="0:12:00" /><div className="flex items-end"><StaticCheckbox label="Refuel after quali" checked /></div></div>
          </SectionPanel>
        </div>
      </div>
    </div>
  );
}

function LiveStage() {
  const driverSummary = [
    { id: 12, name: 'Noah Vale', drive: '2:09:00', share: 22, penalties: 0 },
    { id: 27, name: 'Mia Duval', drive: '1:09:00', share: 12, penalties: 0 },
    { id: 33, name: 'Ethan Rees', drive: '1:06:00', share: 11, penalties: 1 },
    { id: 44, name: 'Lina Hart', drive: '0:36:00', share: 6, penalties: 0 },
  ];

  return (
    <div className="space-y-6">
      <PageIntro title="24H Spa - Pro Class" subtitle="Live Race Dashboard" actions={<div className="flex items-center gap-2"><StatusPill label="LIVE" className="border-acid-green/30 bg-acid-green/10 text-acid-green" /><StatusPill label="PAUSED" className="border-gold/30 bg-gold/10 text-gold" /></div>} />

      <div className="rounded-lg border border-safety-red/30 bg-safety-red/10 px-4 py-2 font-telemetry text-xs uppercase tracking-wider text-safety-red">Blackout period - 20-lap penalty if you pit now (00:14:00 until open)</div>
      <div className="rounded-lg border-2 border-safety-red/30 bg-safety-red/10 px-4 py-3"><div className="flex items-center justify-between gap-3"><span className="font-telemetry text-sm uppercase text-safety-red">Penalty: 150s passage required</span><span className="rounded border border-safety-red/40 bg-safety-red/20 px-3 py-1 font-telemetry text-xs uppercase text-safety-red">Mark Served</span></div></div>

      <div className="space-y-3">
        <div className="flex flex-wrap gap-3">
          <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('ghost')}`}>View Config</button>
          <div className="rounded-lg border border-gold/30 bg-gold/10 px-4 py-2 text-sm text-chalk">Total laps: <span className="rounded border border-steel/20 bg-asphalt px-2 py-1">32</span> <span className="ml-2 rounded bg-gold px-3 py-1 font-telemetry text-xs uppercase text-white">Confirm Pit In</span></div>
          <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('gold')}`}>Re-Optimize</button>
          <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('gold')}`}>Pause</button>
          <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('gold')}`}>Tech Stop</button>
        </div>
        <div className="flex flex-wrap gap-3">
          <div className="rounded-lg border border-acid-green/30 bg-acid-green/10 px-4 py-2 text-sm text-chalk">Kart #: <span className="rounded border border-steel/20 bg-asphalt px-2 py-1">42</span> <span className="ml-2 rounded bg-acid-green px-3 py-1 font-telemetry text-xs uppercase text-asphalt">Pit Out</span></div>
          <div className="rounded-lg border border-safety-red/30 bg-safety-red/10 px-4 py-2 text-sm text-chalk">Penalty form: pit_passage / reason / 1 lap / 150s</div>
          <div className="rounded-lg border border-safety-red/30 bg-safety-red/10 px-4 py-2 text-sm text-chalk">Finish race? <span className="ml-2 rounded bg-safety-red px-3 py-1 font-telemetry text-xs uppercase text-white">Confirm</span></div>
        </div>
      </div>

      <div className="rounded-lg border border-steel/20 bg-concrete p-6">
        <div className="mb-4 flex items-center justify-between"><div><p className="mb-1 font-telemetry text-xs uppercase tracking-wider text-steel">Elapsed</p><p className="font-monument text-4xl text-chalk">11:48:12</p></div><div className="text-right"><p className="mb-1 font-telemetry text-xs uppercase tracking-wider text-steel">Remaining</p><p className="font-monument text-4xl text-chalk">12:11:48</p></div></div>
        <div className="h-3 overflow-hidden rounded-full bg-asphalt"><div className="h-full w-[49%] bg-acid-green" /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <DetailCard title="Fuel" rows={[['Current', '18.4 kg'], ['Burn Rate', '0.26 kg/min'], ['Autonomy', '1:10:00']]} />
        <DetailCard title="In Pit" rows={[['Pit timer', '0:41'], ['Driver change', 'Yes'], ['Kart swap', '#42']]} />
        <DetailCard title="Next Driver" rows={[['Name', 'Noah Vale'], ['Planned duration', '1:03:00'], ['Sleep state', 'Wake now']]} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.9fr]">
        <TableCard title="Driver Summary">
          <table className="w-full">
            <thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Drive</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">% of Race</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Penalties</th></tr></thead>
            <tbody>{driverSummary.map((row) => <tr key={row.id} className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk"><div className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ backgroundColor: driverColors[row.id as keyof typeof driverColors] }} />{row.name}</div></td><td className="px-4 py-3 text-sm text-chalk">{row.drive}</td><td className="px-4 py-3 text-sm text-chalk">{row.share}%</td><td className="px-4 py-3 text-sm text-chalk">{row.penalties}</td></tr>)}</tbody>
          </table>
        </TableCard>
        <TableCard title="Team Messages"><div className="p-4"><MessageLog messages={messages} /></div></TableCard>
      </div>

      <TableCard title="Stint Log">
        <table className="w-full min-w-[980px]">
          <thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">#</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Elapsed</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Laps</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Cum. Laps</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Est. End</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Ballast</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Kart</th></tr></thead>
          <tbody>{stints.map((stint) => <tr key={stint.stint_id} className={`border-b border-steel/10 ${stint.status === 'live' ? 'bg-acid-green/5' : ''}`}><td className="px-4 py-3 text-sm text-chalk">{stint.stint_order}</td><td className="px-4 py-3 text-sm text-chalk">{stint.driver_name}</td><td className="px-4 py-3 text-sm text-chalk">{formatDuration(stint.actual_duration_s ?? stint.planned_duration_s)}</td><td className="px-4 py-3 text-sm text-chalk">{30 + stint.stint_order}</td><td className="px-4 py-3 text-sm text-chalk">{130 + stint.stint_order * 31}</td><td className="px-4 py-3 text-sm text-chalk">{formatDuration(stint.stint_order * 3900 + 1200)}</td><td className="px-4 py-3 text-sm text-chalk">{stint.stint_order % 2 === 0 ? '6 kg' : '12 kg'}</td><td className="px-4 py-3 text-sm text-chalk">#{40 + stint.stint_order}</td></tr>)}</tbody>
        </table>
      </TableCard>
    </div>
  );
}

function ReviewStage() {
  const driverStats = [
    { id: 12, name: 'Noah Vale', total: '5:58:00', stints: 5, longest: '1:13:00', shortest: '0:58:00', share: '24.9%' },
    { id: 27, name: 'Mia Duval', total: '5:55:00', stints: 5, longest: '1:11:00', shortest: '1:01:00', share: '24.7%' },
    { id: 33, name: 'Ethan Rees', total: '5:47:00', stints: 5, longest: '1:08:00', shortest: '0:59:00', share: '24.1%' },
    { id: 44, name: 'Lina Hart', total: '5:41:00', stints: 5, longest: '1:07:00', shortest: '0:56:00', share: '23.7%' },
  ];

  const comparison = [
    { order: 1, driver: 'Noah Vale', planned: '1:05:00', actual: '1:04:00', delta: '-1:00', best: '1:01.245', mean: '1:03.401', cv: '1.8%' },
    { order: 2, driver: 'Mia Duval', planned: '1:08:00', actual: '1:09:00', delta: '+1:00', best: '1:01.910', mean: '1:04.220', cv: '2.3%' },
    { order: 3, driver: 'Ethan Rees', planned: '1:07:00', actual: '1:06:00', delta: '-1:00', best: '1:01.476', mean: '1:03.866', cv: '2.0%' },
    { order: 4, driver: 'Lina Hart', planned: '1:04:00', actual: '1:04:00', delta: '0:00', best: '1:02.118', mean: '1:04.611', cv: '2.5%' },
  ];

  return (
    <div className="space-y-6">
      <PageIntro title="24H Spa - Pro Class" subtitle="Spa-Francorchamps - North Star Motorsport - Race Summary" actions={<StatusPill label="FINISHED" className="border-chalk/30 bg-chalk/10 text-chalk" />} />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Race Duration" value="24:00:00" />
        <StatCard label="Drive Time" value="23:21:00" />
        <StatCard label="Pit Time" value="8:42" />
        <StatCard label="Stints" value={20} />
        <StatCard label="Pit Stops" value={8} />
        <StatCard label="Drivers" value={4} />
      </div>

      <div className="space-y-2">
        <h3 className="font-telemetry text-xs uppercase tracking-wider text-steel">Stint Timeline</h3>
        <StintTimeline stints={stints} totalDuration={totalActual} driverColors={driverColors} preferActual />
      </div>

      <TableCard title="Driver Statistics">
        <table className="w-full">
          <thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Total Drive</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Stints</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Longest</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Shortest</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">% of Race</th></tr></thead>
          <tbody>{driverStats.map((row) => <tr key={row.id} className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk"><div className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ backgroundColor: driverColors[row.id as keyof typeof driverColors] }} />{row.name}</div></td><td className="px-4 py-3 text-sm text-chalk">{row.total}</td><td className="px-4 py-3 text-sm text-chalk">{row.stints}</td><td className="px-4 py-3 text-sm text-chalk">{row.longest}</td><td className="px-4 py-3 text-sm text-chalk">{row.shortest}</td><td className="px-4 py-3 text-sm text-chalk">{row.share}</td></tr>)}</tbody>
        </table>
      </TableCard>

      <TableCard title="Planned vs Actual Comparison">
        <table className="w-full min-w-[980px]">
          <thead><tr className="border-b border-steel/20"><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Stint</th><th className="px-4 py-3 text-left font-telemetry text-xs uppercase tracking-wider text-steel">Driver</th><th className="px-4 py-3 text-right font-telemetry text-xs uppercase tracking-wider text-steel">Planned</th><th className="px-4 py-3 text-right font-telemetry text-xs uppercase tracking-wider text-steel">Actual</th><th className="px-4 py-3 text-right font-telemetry text-xs uppercase tracking-wider text-steel">Delta</th><th className="px-4 py-3 text-right font-telemetry text-xs uppercase tracking-wider text-steel">Best Lap</th><th className="px-4 py-3 text-right font-telemetry text-xs uppercase tracking-wider text-steel">Mean Lap</th><th className="px-4 py-3 text-right font-telemetry text-xs uppercase tracking-wider text-steel">CV%</th></tr></thead>
          <tbody>{comparison.map((row) => <tr key={row.order} className="border-b border-steel/10"><td className="px-4 py-3 text-sm text-chalk">{row.order}</td><td className="px-4 py-3 text-sm text-chalk">{row.driver}</td><td className="px-4 py-3 text-right font-telemetry text-sm text-chalk">{row.planned}</td><td className="px-4 py-3 text-right font-telemetry text-sm text-chalk">{row.actual}</td><td className={`px-4 py-3 text-right font-telemetry text-sm ${row.delta.startsWith('+') ? 'text-safety-red' : row.delta === '0:00' ? 'text-steel' : 'text-acid-green'}`}>{row.delta}</td><td className="px-4 py-3 text-right font-telemetry text-sm text-acid-green">{row.best}</td><td className="px-4 py-3 text-right font-telemetry text-sm text-chalk">{row.mean}</td><td className="px-4 py-3 text-right font-telemetry text-sm text-chalk">{row.cv}</td></tr>)}</tbody>
        </table>
      </TableCard>

      <div className="flex flex-wrap items-center gap-3 border-t border-steel/20 pt-2">
        <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('ghost')}`}>Duplicate</button>
        <button type="button" className={`px-4 py-2 font-telemetry text-sm uppercase tracking-wider ${buttonTone('ghost')}`}>View Config</button>
        <button type="button" className="ml-auto border border-steel/30 px-4 py-2 font-telemetry text-sm uppercase tracking-wider text-steel">All Races</button>
      </div>
    </div>
  );
}

export default function StrategyShowcasePage() {
  return (
    <ShowcaseShell
      eyebrow="Race Strategy Showcase"
      title="Refetched strategy surfaces from the real webapp"
      description="Capture atlas for the actual race strategy module: roster, config detail, builder form, live pit wall, and retrospective review."
      links={[
        { href: '/navigation-showcase', label: 'Navigation' },
        { href: '/gamification-showcase', label: 'Gamification' },
        { href: '/reports-showcase', label: 'Reports' },
      ]}
    >
      <ShowcaseSurface eyebrow="Roster" title="Index, quick-start, filters, cards, and empty states"><div id="strategy-showcase-list"><ListStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Config Detail" title="Editable race setup, timeline, drivers, and stint planning"><div id="strategy-showcase-config"><ConfigStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Builder" title="RaceConfigForm sections, tier gating, and endurance-specific planners"><div id="strategy-showcase-builder"><BuilderStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Live Pit Wall" title="Operational controls, race clock, pit lane, and logs"><div id="strategy-showcase-live"><LiveStage /></div></ShowcaseSurface>
      <ShowcaseSurface eyebrow="Review" title="Finished race summary and planned-versus-actual analysis"><div id="strategy-showcase-review"><ReviewStage /></div></ShowcaseSurface>
    </ShowcaseShell>
  );
}
