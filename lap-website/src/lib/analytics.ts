import { hasAnalyticsConsent } from '@/lib/consent';

type EventProps = Record<string, string | number | boolean | undefined>;

function getPlausible():
  | ((event: string, options?: { props?: EventProps }) => void)
  | undefined {
  if (typeof window === 'undefined') return undefined;
  if (!hasAnalyticsConsent()) return undefined;
  const maybePlausible = (window as unknown as Record<string, unknown>).plausible;
  if (typeof maybePlausible !== 'function') return undefined;
  return maybePlausible as (event: string, options?: { props?: EventProps }) => void;
}

function track(event: string, props?: EventProps) {
  const plausible = getPlausible();
  if (!plausible) return;
  plausible(event, { props });
}

async function trackServer(event: string, payload?: Record<string, string | undefined>) {
  if (typeof window === 'undefined') return;
  try {
    await fetch('/api/conversions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        event,
        ...payload,
      }),
    });
  } catch {
    // Do not break UX if conversion forwarding fails.
  }
}

export function getAttributionFromCookie(): Record<string, string> | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('lap_attribution='));
  if (!raw) return undefined;
  const encoded = raw.split('=').slice(1).join('=');
  if (!encoded) return undefined;
  try {
    return JSON.parse(decodeURIComponent(encoded)) as Record<string, string>;
  } catch {
    return undefined;
  }
}

export function getSessionIdFromCookie(): string | undefined {
  if (typeof document === 'undefined') return undefined;
  const raw = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('lap_session_id='));
  if (!raw) return undefined;
  return raw.split('=').slice(1).join('=');
}

// Engagement
export const trackStartGridHold = (durationMs: number) =>
  track('start_grid_hold', { hold_duration_ms: durationMs });
export const trackStartGridComplete = () => track('start_grid_complete');
export const trackS1CornerInteract = (delta: number) =>
  track('s1_corner_interact', { delta_value: delta });
export const trackS1DeepTraceHover = (trace: string) =>
  track('s1_deep_trace_hover', { trace_name: trace });

// Education
export const trackS2PipelineComplete = () => track('s2_pipeline_complete');

// Trust
export const trackS2ProofReveal = (plate: string) =>
  track('s2_proof_reveal', { plate_name: plate });
export const trackGaragePanelExpand = (panel: string) =>
  track('garage_panel_expand', { panel_name: panel });

// Qualification
export const trackS3ModeSelect = (mode: 'b2c' | 'b2b') =>
  track('s3_mode_select', { mode });
export const trackS3ScrubberInteract = (position: number) =>
  track('s3_scrubber_interact', { position });

// Intent
export const trackPitStopEnter = (fromMode: string) =>
  track('pit_stop_enter', { from_mode: fromMode });
export const trackPricingToggle = (period: string) =>
  track('pricing_toggle', { period });
export const trackPricingPlanHover = (plan: string, durationMs: number) =>
  track('pricing_plan_hover', { plan_name: plan, duration_ms: durationMs });
export const trackAddonExpand = () => track('addon_expand');
export const trackFaqExpand = (questionId: number) =>
  track('faq_expand', { question_id: questionId });

// Demo funnel
export const trackDemoCtaClick = (location: string) =>
  track('demo_cta_click', { location });
export const trackDemoFormView = () => track('demo_form_view');

// A/B Experiments — read active variants from cookies
function getExperimentVariants(): Record<string, string> {
  if (typeof document === 'undefined') return {};
  const variants: Record<string, string> = {};
  for (const name of ['lap_exp_hero', 'lap_exp_pricing', 'lap_exp_cta']) {
    const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
    if (match) variants[name] = match[1];
  }
  return variants;
}

/** Track a conversion event with experiment variant context. */
export function trackConversion(goal: string, props?: EventProps) {
  const variants = getExperimentVariants();
  track('conversion', {
    goal,
    ...variants,
    ...props,
  });
}

// Conversion
export const trackCtaClick = (cta: string, location: string, mode: string) => {
  track('cta_click', { cta_name: cta, location, mode });
  trackConversion('cta_click', { cta_name: cta, location, mode });
};
export const trackFormSubmitStart = (formType: string, sourcePath: string) =>
  track('lead_submit_start', { form_type: formType, source_path: sourcePath });
export const trackFormSubmitSuccess = async (formType: string, sourcePath: string) => {
  track('lead_submit_success', { form_type: formType, source_path: sourcePath });
  trackConversion('lead_submit', { form_type: formType, source_path: sourcePath });
  await trackServer('lead_submit_success', { leadType: formType, sourcePath });
};
export const trackFormSubmitError = (formType: string, sourcePath: string, reason: string) =>
  track('lead_submit_error', { form_type: formType, source_path: sourcePath, reason });
export const trackFormFieldBlur = (formType: string, fieldName: string) =>
  track('lead_field_blur', { form_type: formType, field_name: fieldName });
export const trackFormSubmitTiming = (formType: string, durationMs: number) =>
  track('lead_submit_timing', { form_type: formType, duration_ms: durationMs });

// Navigation
export const trackIndexOverlayOpen = (fromSection: string) =>
  track('index_overlay_open', { from_section: fromSection });
export const trackIndexOverlayNav = (toSection: string) =>
  track('index_overlay_nav', { to_section: toSection });
export const trackNavRouteClick = (route: string, location: string) =>
  track('route_click', { route, location });

// Preference
export const trackSoundToggle = (enabled: boolean) =>
  track('sound_toggle', { enabled });
export const trackReducedMotionToggle = (enabled: boolean) =>
  track('reduced_motion_toggle', { enabled });

// Completion
export const trackPodiumReach = (scrollTimeMs: number, sectionsVisited: number) =>
  track('podium_reach', { total_scroll_time_ms: scrollTimeMs, sections_visited: sectionsVisited });
export const trackRestartLap = () => track('restart_lap');
