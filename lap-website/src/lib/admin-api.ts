/**
 * Admin API client for Race Control dashboard.
 * Wraps the standard api client with admin-specific endpoints.
 */

import { api } from './api-client';

/* ── Types ──────────────────────────────────── */

export interface HealthOverview {
  services: Record<string, string>;
  jobs: {
    total_24h: number;
    failed_24h: number;
    queue_depth: number;
    failure_rate_pct: number;
    avg_duration_s: number;
  };
  billing: {
    webhook_total_24h: number;
    webhook_success_rate_pct: number;
  };
  security: {
    login_failures_24h: number;
    rate_limits_24h: number;
  };
}

export interface MetricsSnapshot {
  id: number;
  collected_at: string;
  metrics: Record<string, unknown>;
}

export interface AdminUser {
  id: number;
  email: string;
  plan_tier: string;
  subscription_status: string;
  created_at: string;
  last_login_at?: string;
  display_name?: string;
  is_superadmin?: boolean;
  admin_role?: string;
  workspaces?: Array<{ id: number; name: string; role: string }>;
}

export interface AdminJob {
  job_id: string;
  file_name: string;
  status: string;
  user_id: number;
  workspace_id: number;
  created_at: string;
  duration_s?: number;
  error_message?: string;
  celery_task_id?: string;
  retry_count?: number;
}

export interface JobStats {
  total: number;
  failed: number;
  queue_depth: number;
  p50_duration: number;
  p95_duration: number;
  failure_rate_pct: number;
  top_errors: Array<{ error_class: string; cnt: number }>;
}

export interface Subscription {
  id: number;
  email: string;
  plan_tier: string;
  stripe_subscription_id: string;
  subscription_status: string;
  created_at: string;
}

export interface WebhookEntry {
  id: number;
  stripe_event_id: string;
  event_type: string;
  processing_status: string;
  error_message?: string;
  created_at: string;
}

export interface RevenueSnapshot {
  tier_breakdown: Array<{ plan_tier: string; cnt: number }>;
  total_active: number;
  churned_30d: number;
}

export interface Anomaly {
  anomaly_type: string;
  severity: string;
  user_id?: number;
  workspace_id?: number;
  details: Record<string, unknown>;
}

export interface SecurityEvent {
  id: number;
  event_type: string;
  user_id?: number;
  ip_address?: string;
  severity: string;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  admin_user_id: number;
  action: string;
  target_type?: string;
  target_id?: string;
  reason?: string;
  details_json?: string;
  created_at: string;
}

export interface Incident {
  id: number;
  admin_user_id: number;
  title: string;
  body?: string;
  severity: string;
  status: string;
  created_at: string;
  resolved_at?: string;
}

/* ── API ──────────────────────────────────── */

export const adminApi = {
  // Health
  healthOverview: () => api.get<HealthOverview>('/admin/health/overview'),
  healthMetrics: (hours = 6) => api.get<MetricsSnapshot[]>(`/admin/health/metrics?hours=${hours}`),

  // Users
  listUsers: (params?: { q?: string; plan_tier?: string; limit?: number; cursor?: number }) => {
    const qs = new URLSearchParams();
    if (params?.q) qs.set('q', params.q);
    if (params?.plan_tier) qs.set('plan_tier', params.plan_tier);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', String(params.cursor));
    return api.get<AdminUser[]>(`/admin/users?${qs}`);
  },
  getUser: (id: number) => api.get<AdminUser>(`/admin/users/${id}`),
  getUserTimeline: (id: number) => api.get<unknown[]>(`/admin/users/${id}/timeline`),
  invalidateSessions: (id: number, reason: string) =>
    api.post<{ sessions_revoked: number }>(`/admin/users/${id}/invalidate-sessions`, { reason }),

  // Jobs
  listJobs: (params?: { status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    return api.get<AdminJob[]>(`/admin/jobs?${qs}`);
  },
  getJob: (id: string) => api.get<AdminJob>(`/admin/jobs/${id}`),
  jobStats: () => api.get<JobStats>('/admin/jobs/stats'),
  retryJob: (id: string, reason: string) => api.post(`/admin/jobs/${id}/retry`, { reason }),
  cancelJob: (id: string, reason: string) => api.post(`/admin/jobs/${id}/cancel`, { reason }),

  // Billing
  listSubscriptions: () => api.get<Subscription[]>('/admin/billing/subscriptions'),
  listWebhooks: (params?: { status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    return api.get<WebhookEntry[]>(`/admin/billing/webhooks?${qs}`);
  },
  revenue: () => api.get<RevenueSnapshot>('/admin/billing/revenue'),
  reconciliation: () => api.get<AdminUser[]>('/admin/billing/reconciliation'),
  healMismatch: (userId: number, reason: string) =>
    api.post(`/admin/billing/reconciliation/${userId}/heal`, { reason }),

  // Entitlements
  listPlans: () => api.get<Record<string, unknown>[]>('/admin/entitlements/plans'),
  getUsage: (workspaceId: number) => api.get<{ workspace_id: number; usage: Record<string, number> }>(`/admin/entitlements/usage/${workspaceId}`),
  listAnomalies: () => api.get<Anomaly[]>('/admin/entitlements/anomalies'),
  createOverride: (data: { user_id?: number; workspace_id?: number; override_key: string; override_value: string; reason: string }) =>
    api.post<{ override_id: number }>('/admin/entitlements/overrides', data),
  refreshTier: (userId: number) => api.post(`/admin/entitlements/refresh/${userId}`),

  // Email
  emailStats: () => api.get<{ total_sent: number; verified: number; verification_rate_pct: number }>('/admin/email/stats'),
  resendVerification: (userId: number, reason: string) =>
    api.post(`/admin/email/resend-verification/${userId}`, { reason }),

  // Security
  listSecurityEvents: (params?: { type?: string; severity?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.type) qs.set('type', params.type);
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.limit) qs.set('limit', String(params.limit));
    return api.get<SecurityEvent[]>(`/admin/security/events?${qs}`);
  },
  listAuditLog: (params?: { action?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.action) qs.set('action', params.action);
    if (params?.limit) qs.set('limit', String(params.limit));
    return api.get<AuditEntry[]>(`/admin/security/audit-log?${qs}`);
  },
  authFailures: () => api.get<{ top_ips: Array<{ ip_address: string; cnt: number }>; top_users: Array<{ user_id: number; cnt: number }> }>('/admin/security/auth-failures'),

  // Incidents
  createIncident: (data: { title: string; body?: string; severity?: string }) =>
    api.post<{ incident_id: number }>('/admin/incidents', data),
  updateIncident: (id: number, data: { status?: string; body?: string; severity?: string }) =>
    api.post(`/admin/incidents/${id}`, data), // PATCH via POST for simplicity
  listIncidents: (params?: { status?: string }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    return api.get<Incident[]>(`/admin/incidents?${qs}`);
  },

  // Infra
  storage: () => api.get<{ db_size_bytes: number; table_count?: number }>('/admin/infra/storage'),
  maintenanceStatus: () => api.get<{ enabled: boolean; message?: string }>('/admin/infra/maintenance'),
  toggleMaintenance: (enabled: boolean, message: string, reason?: string) =>
    api.post('/admin/infra/maintenance', { enabled, message, reason }),
};
