'use client';

import Link from 'next/link';
import { DriverReport } from '@/components/app/endurance/DriverReport';
import { StintReport } from '@/components/app/endurance/StintReport';
import { TeamReport } from '@/components/app/endurance/TeamReport';
import type { DriverReport as DriverReportType, Stint, TeamReport as TeamReportType } from '@/components/app/endurance/types';
import { ShowcaseShell, ShowcaseSurface } from '@/components/showcase/ShowcaseShell';

const enduranceStints: Stint[] = [
  {
    stint_number: 1,
    start_lap: 1,
    end_lap: 28,
    lap_count: 28,
    pit_lap_number: 29,
    pit_lap_time_s: 159.4,
    condition: 'dry',
    driver_name: 'Noah Vale',
    driver_id: 12,
    best_lap_s: 94.2,
    mean_lap_s: 95.1,
    consistency_cv_pct: 0.9,
    pace_fade_pct: 0.4,
    scores: { pace: 22.6, consistency: 21.9, robustness: 20.8 },
  },
  {
    stint_number: 2,
    start_lap: 29,
    end_lap: 56,
    lap_count: 28,
    pit_lap_number: 57,
    pit_lap_time_s: 168.3,
    condition: 'dry',
    driver_name: 'Mia Duval',
    driver_id: 27,
    best_lap_s: 94.6,
    mean_lap_s: 95.6,
    consistency_cv_pct: 1.1,
    pace_fade_pct: 0.6,
    scores: { pace: 21.9, consistency: 20.7, robustness: 20.1 },
  },
  {
    stint_number: 3,
    start_lap: 57,
    end_lap: 84,
    lap_count: 28,
    pit_lap_number: 85,
    pit_lap_time_s: 173.9,
    condition: 'mixed',
    driver_name: 'Ethan Rees',
    driver_id: 33,
    best_lap_s: 95.0,
    mean_lap_s: 96.1,
    consistency_cv_pct: 1.4,
    pace_fade_pct: 0.9,
    scores: { pace: 20.8, consistency: 19.9, robustness: 19.4 },
  },
  {
    stint_number: 4,
    start_lap: 85,
    end_lap: 113,
    lap_count: 29,
    pit_lap_number: null,
    pit_lap_time_s: null,
    condition: 'dry',
    driver_name: 'Noah Vale',
    driver_id: 12,
    best_lap_s: 94.4,
    mean_lap_s: 95.3,
    consistency_cv_pct: 0.8,
    pace_fade_pct: 0.3,
    scores: { pace: 22.1, consistency: 22.4, robustness: 21.1 },
  },
];

const driverReports: Record<string, DriverReportType> = {
  'Noah Vale': {
    driver_name: 'Noah Vale',
    total_laps: 57,
    total_stints: 2,
    stints: [enduranceStints[0], enduranceStints[3]],
    best_lap_s: 94.2,
    mean_lap_s: 95.2,
    consistency_cv_pct: 0.8,
    best_per_stint: [
      { stint_number: 1, best_lap_s: 94.2 },
      { stint_number: 4, best_lap_s: 94.4 },
    ],
    scores: { pace: 22.4, consistency: 22.1, robustness: 21.0 },
  },
  'Mia Duval': {
    driver_name: 'Mia Duval',
    total_laps: 28,
    total_stints: 1,
    stints: [enduranceStints[1]],
    best_lap_s: 94.6,
    mean_lap_s: 95.6,
    consistency_cv_pct: 1.1,
    best_per_stint: [{ stint_number: 2, best_lap_s: 94.6 }],
    scores: { pace: 21.9, consistency: 20.7, robustness: 20.1 },
  },
  'Ethan Rees': {
    driver_name: 'Ethan Rees',
    total_laps: 28,
    total_stints: 1,
    stints: [enduranceStints[2]],
    best_lap_s: 95.0,
    mean_lap_s: 96.1,
    consistency_cv_pct: 1.4,
    best_per_stint: [{ stint_number: 3, best_lap_s: 95.0 }],
    scores: { pace: 20.8, consistency: 19.9, robustness: 19.4 },
  },
};

const teamReport = {
  total_laps: 113,
  total_time_s: 10834,
  total_stints: 4,
  drivers: ['Noah Vale', 'Mia Duval', 'Ethan Rees'],
  driver_comparison: Object.values(driverReports).map((driver) => ({
    ...driver,
    traffic_count:
      driver.driver_name === 'Mia Duval' ? 2 : driver.driver_name === 'Ethan Rees' ? 3 : 1,
    traffic_total_s:
      driver.driver_name === 'Mia Duval' ? 3.2 : driver.driver_name === 'Ethan Rees' ? 5.1 : 1.7,
    scores: {
      ...driver.scores,
      execution:
        driver.driver_name === 'Noah Vale'
          ? 21.4
          : driver.driver_name === 'Mia Duval'
            ? 20.3
            : 19.2,
    },
  })),
  scores: {
    pace: 22.1,
    consistency: 21.0,
    robustness: 20.2,
    execution: 20.4,
  },
  total_time_loss_s: 14.7,
  traffic_total_s: 10.0,
  traffic_count: 6,
  pit_time_loss_s: 4.7,
  n_pits: 3,
  avg_pit_s: 35,
  pit_threshold_s: 30,
  coaching: [
    {
      priority: 'high',
      message: 'Reduce pit release hesitation by pre-calling the tire and radio sequence one lap earlier.',
    },
    {
      priority: 'medium',
      message: 'Ethan lost the most time in mixed conditions. Rehearse brake migration presets before the next stint.',
    },
  ],
  pit_stops: [
    { stint_number: 1, driver_name: 'Noah Vale', pit_duration_s: 32 },
    { stint_number: 2, driver_name: 'Mia Duval', pit_duration_s: 36 },
    { stint_number: 3, driver_name: 'Ethan Rees', pit_duration_s: 37 },
  ],
} as TeamReportType;

const selectedStint = {
  ...enduranceStints[2],
  session_id: 'session-endurance-spa',
  traffic_count: 2,
  traffic_total_s: 3.4,
  traffic_losses: [
    { lap_time_s: 98.2, neighbor_mean_s: 96.4, time_lost_s: 1.8 },
    { lap_time_s: 97.9, neighbor_mean_s: 96.3, time_lost_s: 1.6 },
  ],
} as Stint;

function EnduranceHeader() {
  return (
    <div className="rounded-[26px] border border-white/10 bg-[linear-gradient(180deg,rgba(15,15,15,0.96),rgba(7,7,7,0.95))] p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <Link href="/reports-showcase" className="text-sm font-body text-steel transition-colors hover:text-chalk">
              Reports
            </Link>
            <span className="text-steel/60">/</span>
            <span className="text-sm font-body text-steel">Endurance</span>
          </div>
          <h1 className="text-2xl font-monument text-chalk tracking-tight">24H Spa / Team race report</h1>
          <p className="mt-1 text-sm font-body text-steel">
            North Star Motorsport • 3 drivers • 4 stints • Team / driver / stint drill-down
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-full border border-acid-green/25 bg-acid-green/10 px-3 py-1 font-telemetry text-[10px] uppercase tracking-[0.16em] text-acid-green">
            Endurance
          </span>
          <button
            type="button"
            className="rounded-lg border border-steel/20 bg-concrete px-3 py-2 text-sm font-body text-chalk"
          >
            Export PDF
          </button>
          <button
            type="button"
            className="rounded-lg border border-steel/20 bg-concrete px-3 py-2 text-sm font-body text-chalk"
          >
            Share Report
          </button>
        </div>
      </div>

      <div className="mt-8 flex items-center gap-1 border-b border-steel/10">
        {['Team Report', 'Driver Report', 'Stint Report'].map((tab, index) => (
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
      </div>
    </div>
  );
}

export default function EnduranceReportsShowcasePage() {
  return (
    <ShowcaseShell
      eyebrow="Endurance Race Report"
      title="Team, driver, and stint reporting"
      description="Capture surface for the real endurance report stack: race overview, strategy timeline, driver comparison, selected driver detail, and stint incident analysis."
      links={[
        { href: '/reports-showcase', label: 'Reports Hub' },
        { href: '/reports-showcase/normal', label: 'Normal Report' },
        { href: '/strategy-showcase', label: 'Race Strategy' },
      ]}
    >
      <ShowcaseSurface eyebrow="Header" title="Endurance report identity and section switcher">
        <div id="endurance-report-header">
          <EnduranceHeader />
        </div>
      </ShowcaseSurface>

      <ShowcaseSurface eyebrow="Team View" title="Race report, timeline, and driver comparison">
        <div id="endurance-report-team">
          <TeamReport
            report={teamReport}
            stints={enduranceStints}
            pitThreshold={30}
            onSelectDriver={() => {}}
          />
        </div>
      </ShowcaseSurface>

      <ShowcaseSurface eyebrow="Driver View" title="Selected driver report">
        <div id="endurance-report-driver">
          <DriverReport
            report={driverReports['Noah Vale']}
            onSelectStint={() => {}}
            onBack={() => {}}
          />
        </div>
      </ShowcaseSurface>

      <ShowcaseSurface eyebrow="Stint View" title="Stint-level incident and score drill-down">
        <div id="endurance-report-stint">
          <StintReport
            sessionId="session-endurance-spa"
            stint={selectedStint}
            onBack={() => {}}
            trackName="Spa-Francorchamps"
            kartName="Ligier JS2R"
          />
        </div>
      </ShowcaseSurface>
    </ShowcaseShell>
  );
}
