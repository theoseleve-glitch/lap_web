"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-client";

type AdminOverview = {
  business: {
    signups_total: number; signups_7d: number; active_subscribers: number;
    trial_active: number; founding_50_used: number; churned_30d: number;
    upload_volume_30d: number;
  };
  product: {
    dau_today: number; wau_7d: number; total_events_30d: number;
    unique_features_30d: number;
    funnel: { upload: number; analyze: number; export: number };
  };
  live_ops: {
    jobs_active: number; jobs_failed_24h: number; jobs_completed_24h: number;
    queue_backlog: number; error_rate_5xx_pct: number; p95_latency_ms: number | null;
  };
  growth: {
    marketing_pageviews_7d: number; signup_clicked_7d: number; pricing_viewed_7d: number;
    demo_viewed_7d: number; waitlist_submitted_7d: number; waitlist_confirmed_7d: number;
    download_clicked_7d: number;
  };
  generated_at: string;
  cached: boolean;
};

function Stat({ label, value, tone = "neutral" }: {
  label: string; value: string | number; tone?: "neutral" | "good" | "bad";
}) {
  const valueClass =
    tone === "good" ? "text-acid-green" : tone === "bad" ? "text-safety-red" : "text-chalk";
  return (
    <div className="rounded-lg border border-steel/30 bg-concrete p-4">
      <p className="font-telemetry text-[10px] uppercase tracking-[0.12em] text-steel">{label}</p>
      <p className={`mt-1 font-telemetry text-2xl tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}

function Lens({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 font-monument text-sm uppercase tracking-wide text-chalk">{title}</h2>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">{children}</div>
    </section>
  );
}

export default function AdminOverviewPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["admin-overview"],
    queryFn: () => apiFetch<AdminOverview>("/admin/overview"),
    refetchInterval: 20000,
  });

  const b = data?.business;
  const p = data?.product;
  const o = data?.live_ops;
  const gr = data?.growth;
  const dash = (n: number | null | undefined) => (n ?? "—");

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="font-monument text-2xl text-chalk">Overview</h1>
        {data && (
          <span className="font-telemetry text-[10px] uppercase tracking-[0.12em] text-steel">
            {data.cached ? "cached" : "live"} · {new Date(data.generated_at).toLocaleTimeString()}
          </span>
        )}
      </div>

      {isLoading && <p className="font-body text-sm text-steel">Loading cockpit…</p>}

      <Lens title="Business Health">
        <Stat label="Signups (total)" value={dash(b?.signups_total)} />
        <Stat label="Signups (7d)" value={dash(b?.signups_7d)} tone="good" />
        <Stat label="Active subs" value={dash(b?.active_subscribers)} tone="good" />
        <Stat label="Trials active" value={dash(b?.trial_active)} />
        <Stat label="Founding-50 used" value={dash(b?.founding_50_used)} />
        <Stat label="Churned (30d)" value={dash(b?.churned_30d)} tone={b && b.churned_30d > 0 ? "bad" : "neutral"} />
        <Stat label="Uploads (30d)" value={dash(b?.upload_volume_30d)} />
      </Lens>

      <Lens title="Product Usage">
        <Stat label="DAU (today)" value={dash(p?.dau_today)} tone="good" />
        <Stat label="WAU (7d)" value={dash(p?.wau_7d)} />
        <Stat label="Events (30d)" value={dash(p?.total_events_30d)} />
        <Stat label="Features used (30d)" value={dash(p?.unique_features_30d)} />
        <Stat label="Funnel · upload" value={dash(p?.funnel.upload)} />
        <Stat label="Funnel · analyze" value={dash(p?.funnel.analyze)} />
        <Stat label="Funnel · export" value={dash(p?.funnel.export)} />
      </Lens>

      <Lens title="Live Ops">
        <Stat label="Jobs active" value={dash(o?.jobs_active)} />
        <Stat label="Failed (24h)" value={dash(o?.jobs_failed_24h)} tone={o && o.jobs_failed_24h > 0 ? "bad" : "neutral"} />
        <Stat label="Completed (24h)" value={dash(o?.jobs_completed_24h)} tone="good" />
        <Stat label="Queue backlog" value={dash(o?.queue_backlog)} />
        <Stat label="5xx rate %" value={dash(o?.error_rate_5xx_pct)} tone={o && o.error_rate_5xx_pct > 1 ? "bad" : "neutral"} />
        <Stat label="p95 latency" value={o?.p95_latency_ms != null ? `${o.p95_latency_ms}ms` : "—"} />
      </Lens>

      <Lens title="Growth">
        <Stat label="Pageviews (7d)" value={dash(gr?.marketing_pageviews_7d)} />
        <Stat label="Signup clicks (7d)" value={dash(gr?.signup_clicked_7d)} />
        <Stat label="Pricing views (7d)" value={dash(gr?.pricing_viewed_7d)} />
        <Stat label="Demo views (7d)" value={dash(gr?.demo_viewed_7d)} />
        <Stat label="Waitlist submitted (7d)" value={dash(gr?.waitlist_submitted_7d)} />
        <Stat label="Waitlist confirmed (7d)" value={dash(gr?.waitlist_confirmed_7d)} tone="good" />
        <Stat label="Downloads (7d)" value={dash(gr?.download_clicked_7d)} />
      </Lens>
    </div>
  );
}
