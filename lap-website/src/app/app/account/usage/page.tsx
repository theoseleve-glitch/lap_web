'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { PageIntro } from '@/components/ui/PageIntro';
import { apiFetch } from '@/lib/api-client';

/* ── Types ────────────────────────────────────────────────── */

interface UsageMetric {
  used: number;
  limit: number;
  remaining: number;
  resets: string | null;
}

interface UsageData {
  reports: UsageMetric;
  uploads: UsageMetric;
}

interface EntitlementsData {
  plan: string;
  entitlements: {
    reports_per_month: number;
    uploads_per_month: number;
    raw_retention_days: number;
    report_retention: string;
    comparison_progress: boolean;
    coaching_drills: boolean;
    viz_workspace: boolean;
    strategy_dashboard: string;
    live_pace: boolean;
    pit_planning: boolean;
    pdf_reports: boolean;
    api_access: boolean;
    track_management: string;
    max_workspace_members: number;
  };
}

/* ── Constants ────────────────────────────────────────────── */

const PLAN_LABELS: Record<string, string> = {
  demo: 'Demo',
  racer: 'Racer',
  'world-class': 'World-Class',
  b2b: 'Enterprise',
};

const PLAN_STYLES: Record<string, string> = {
  demo: 'bg-steel/20 text-steel',
  racer: 'bg-acid-green/20 text-acid-green',
  'world-class': 'bg-racing-purple/20 text-racing-purple',
  b2b: 'bg-marshal-yellow/20 text-marshal-yellow',
};

/* ── Progress Bar Component ───────────────────────────────── */

function UsageBar({
  label,
  used,
  limit,
  resets,
}: {
  label: string;
  used: number;
  limit: number;
  resets: string | null;
}) {
  const isUnlimited = limit === -1;
  const pct = isUnlimited ? 0 : limit === 0 ? 100 : Math.min((used / limit) * 100, 100);
  const barColor =
    pct >= 100
      ? 'bg-safety-red'
      : pct >= 80
        ? 'bg-marshal-yellow'
        : 'bg-acid-green';

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-chalk text-sm font-body">{label}</span>
        <span className="text-steel text-xs font-telemetry">
          {used} / {isUnlimited ? 'unlimited' : limit} used
        </span>
      </div>
      <div className="w-full h-2 bg-steel/20 rounded-full overflow-hidden">
        {!isUnlimited && (
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      {resets && (
        <p className="text-steel text-[10px] font-body mt-1">
          Resets {new Date(resets).toLocaleDateString()}
        </p>
      )}
    </div>
  );
}

/* ── Feature Row Component ────────────────────────────────── */

function FeatureRow({
  label,
  value,
}: {
  label: string;
  value: string | boolean | number | null;
}) {
  const isBoolean = typeof value === 'boolean';
  return (
    <div className="flex items-center justify-between py-2 border-b border-steel/10 last:border-0">
      <span className="text-steel text-sm font-body">{label}</span>
      {isBoolean ? (
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-telemetry ${
            value ? 'bg-acid-green/20 text-acid-green' : 'bg-steel/20 text-steel'
          }`}
        >
          {value ? 'Enabled' : 'Disabled'}
        </span>
      ) : (
        <span className="text-chalk text-sm font-telemetry">
          {value === null || value === -1 ? 'Unlimited' : String(value)}
        </span>
      )}
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────── */

export default function UsagePage() {
  const { data: usage, isLoading: usageLoading } = useQuery<UsageData>({
    queryKey: ['account', 'usage'],
    queryFn: () => apiFetch<UsageData>('/account/usage'),
    staleTime: 30_000,
  });

  const { data: entitlements, isLoading: entitlementsLoading } = useQuery<EntitlementsData>({
    queryKey: ['account', 'entitlements'],
    queryFn: () => apiFetch<EntitlementsData>('/account/entitlements'),
    staleTime: 60_000,
  });

  const plan = entitlements?.plan || 'demo';
  const isTopPlan = plan === 'world-class' || plan === 'b2b';

  return (
    <div>
      <PageIntro title="Usage & Limits" subtitle="Monitor your plan usage and feature entitlements" />

      {/* ── Current Plan ──────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-4 mb-6">
        {entitlementsLoading ? (
          <div className="animate-pulse h-8 bg-steel/10 rounded" />
        ) : (
          <div className="flex items-center gap-3">
            <span className="font-monument text-lg text-chalk">
              {PLAN_LABELS[plan] || plan}
            </span>
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-telemetry ${
                PLAN_STYLES[plan] || PLAN_STYLES.demo
              }`}
            >
              {plan}
            </span>
          </div>
        )}
      </div>

      {/* ── Monthly Usage ─────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h3 className="font-monument text-sm text-chalk mb-4">Monthly Usage</h3>
        {usageLoading ? (
          <div className="animate-pulse space-y-4">
            <div className="h-12 bg-steel/10 rounded" />
            <div className="h-12 bg-steel/10 rounded" />
          </div>
        ) : usage ? (
          <div className="space-y-5">
            <UsageBar
              label="Reports"
              used={usage.reports.used}
              limit={usage.reports.limit}
              resets={usage.reports.resets}
            />
            <UsageBar
              label="Uploads"
              used={usage.uploads.used}
              limit={usage.uploads.limit}
              resets={usage.uploads.resets}
            />
          </div>
        ) : (
          <p className="text-steel text-sm font-body">Unable to load usage data</p>
        )}
      </div>

      {/* ── Plan Features ─────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-6 mb-6">
        <h3 className="font-monument text-sm text-chalk mb-4">Plan Features</h3>
        {entitlementsLoading ? (
          <div className="animate-pulse space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-8 bg-steel/10 rounded" />
            ))}
          </div>
        ) : entitlements ? (
          <div>
            <FeatureRow
              label="Reports per month"
              value={entitlements.entitlements.reports_per_month}
            />
            <FeatureRow
              label="Uploads per month"
              value={entitlements.entitlements.uploads_per_month}
            />
            <FeatureRow
              label="Data retention"
              value={`${entitlements.entitlements.raw_retention_days} days`}
            />
            <FeatureRow
              label="Lap comparison"
              value={entitlements.entitlements.comparison_progress}
            />
            <FeatureRow
              label="Coaching drills"
              value={entitlements.entitlements.coaching_drills}
            />
            <FeatureRow
              label="Visualization Workspace"
              value={entitlements.entitlements.viz_workspace}
            />
            <FeatureRow
              label="Strategy dashboard"
              value={entitlements.entitlements.strategy_dashboard}
            />
            <FeatureRow
              label="Live pace"
              value={entitlements.entitlements.live_pace}
            />
            <FeatureRow
              label="Pit planning"
              value={entitlements.entitlements.pit_planning}
            />
            <FeatureRow
              label="PDF reports"
              value={entitlements.entitlements.pdf_reports}
            />
            <FeatureRow
              label="API access"
              value={entitlements.entitlements.api_access}
            />
            <FeatureRow
              label="Track management"
              value={entitlements.entitlements.track_management}
            />
            <FeatureRow
              label="Workspace members"
              value={entitlements.entitlements.max_workspace_members}
            />
          </div>
        ) : (
          <p className="text-steel text-sm font-body">Unable to load entitlements</p>
        )}
      </div>

      {/* ── Upgrade CTA ───────────────────────────────── */}
      {!isTopPlan && (
        <div className="bg-concrete rounded-lg border border-acid-green/30 p-6 text-center">
          <p className="text-chalk font-monument text-sm mb-2">Need more?</p>
          <p className="text-steel text-sm font-body mb-4">
            Upgrade your plan for higher limits, advanced features, and priority support.
          </p>
          <Link
            href="/app/account/billing/upgrade"
            className="inline-block bg-gold text-asphalt font-telemetry text-sm px-6 py-2 rounded-md hover:brightness-110 transition"
          >
            Upgrade Plan
          </Link>
        </div>
      )}
    </div>
  );
}
