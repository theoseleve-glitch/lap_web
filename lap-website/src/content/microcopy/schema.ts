/**
 * Microcopy schema — metadata for each key in en.json / fr.json.
 * Used for documentation and lint validation, not at runtime.
 */

export interface MicrocopyEntry {
  key: string;
  vars?: string[];
  tone: 'neutral' | 'urgent' | 'helpful' | 'celebratory';
  category: 'error' | 'empty' | 'tooltip' | 'banner';
}

export const MICROCOPY_SCHEMA: MicrocopyEntry[] = [
  // ── Errors: Auth ──
  { key: 'error.auth.invalidCredentials', tone: 'neutral', category: 'error' },
  { key: 'error.auth.sessionExpired', tone: 'neutral', category: 'error' },
  { key: 'error.auth.accountLocked', vars: ['minutes'], tone: 'neutral', category: 'error' },
  { key: 'error.auth.emailNotVerified', tone: 'helpful', category: 'error' },
  { key: 'error.auth.oauthFailed', vars: ['provider'], tone: 'neutral', category: 'error' },
  { key: 'error.auth.twoFactorInvalid', tone: 'neutral', category: 'error' },

  // ── Errors: Billing ──
  { key: 'error.billing.paymentFailed', tone: 'urgent', category: 'error' },
  { key: 'error.billing.cardDeclined', tone: 'neutral', category: 'error' },
  { key: 'error.billing.subscriptionExpired', tone: 'urgent', category: 'error' },
  { key: 'error.billing.invoiceUnpaid', tone: 'urgent', category: 'error' },
  { key: 'error.billing.planLimitReached', tone: 'helpful', category: 'error' },

  // ── Errors: Upload ──
  { key: 'error.upload.fileTooLarge', vars: ['limit'], tone: 'neutral', category: 'error' },
  { key: 'error.upload.invalidFormat', tone: 'helpful', category: 'error' },
  { key: 'error.upload.parseFailed', tone: 'neutral', category: 'error' },
  { key: 'error.upload.noGpsData', tone: 'neutral', category: 'error' },
  { key: 'error.upload.duplicateSession', tone: 'neutral', category: 'error' },
  { key: 'error.upload.quotaExceeded', tone: 'urgent', category: 'error' },

  // ── Errors: Analysis ──
  { key: 'error.analysis.pipelineFailed', tone: 'neutral', category: 'error' },
  { key: 'error.analysis.noLapsDetected', tone: 'helpful', category: 'error' },
  { key: 'error.analysis.trackNotRecognized', tone: 'helpful', category: 'error' },
  { key: 'error.analysis.insufficientData', tone: 'neutral', category: 'error' },

  // ── Errors: Generic ──
  { key: 'error.generic.networkError', tone: 'neutral', category: 'error' },
  { key: 'error.generic.serverError', tone: 'neutral', category: 'error' },
  { key: 'error.generic.notFound', tone: 'neutral', category: 'error' },
  { key: 'error.generic.forbidden', tone: 'neutral', category: 'error' },
  { key: 'error.generic.rateLimited', tone: 'neutral', category: 'error' },

  // ── Empty states ──
  { key: 'empty.sessions', tone: 'helpful', category: 'empty' },
  { key: 'empty.laps', tone: 'neutral', category: 'empty' },
  { key: 'empty.comparison', tone: 'helpful', category: 'empty' },
  { key: 'empty.corners', tone: 'neutral', category: 'empty' },
  { key: 'empty.coaching', tone: 'neutral', category: 'empty' },
  { key: 'empty.tracks', tone: 'helpful', category: 'empty' },
  { key: 'empty.drivers', tone: 'neutral', category: 'empty' },
  { key: 'empty.reports', tone: 'neutral', category: 'empty' },
  { key: 'empty.search', vars: ['query'], tone: 'neutral', category: 'empty' },
  { key: 'empty.notifications', tone: 'celebratory', category: 'empty' },

  // ── Tooltips ──
  { key: 'tooltip.delta', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.optimalLap', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.confidence', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.pace', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.consistency', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.execution', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.robustness', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.timeLoss', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.ggDiagram', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.heatmap', tone: 'neutral', category: 'tooltip' },
  { key: 'tooltip.sectorSplit', tone: 'neutral', category: 'tooltip' },

  // ── Banners ──
  { key: 'banner.pastDue', tone: 'urgent', category: 'banner' },
  { key: 'banner.degradedAnalysis', tone: 'neutral', category: 'banner' },
  { key: 'banner.maintenance', vars: ['date'], tone: 'neutral', category: 'banner' },
  { key: 'banner.newFeature', vars: ['feature', 'link'], tone: 'celebratory', category: 'banner' },
  { key: 'banner.trialEnding', vars: ['days'], tone: 'urgent', category: 'banner' },
  { key: 'banner.exportReady', vars: ['link'], tone: 'celebratory', category: 'banner' },
  { key: 'banner.planDowngraded', tone: 'urgent', category: 'banner' },
];
