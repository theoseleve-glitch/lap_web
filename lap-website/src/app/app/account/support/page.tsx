'use client';

import { useState, useId } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { PageHeader } from '@/components/app';
import { apiFetch } from '@/lib/api-client';
import { useEntitlements } from '@/hooks/useEntitlements';

/* ── Types ────────────────────────────────────────────────── */

interface TicketResponse {
  ticket_id: number;
  status: string;
  message: string;
}

interface Ticket {
  id: number;
  issue_type: string;
  description: string;
  status: string;
  created_at: string | null;
}

const ISSUE_TYPES = [
  { value: 'bug', label: 'Bug Report' },
  { value: 'billing', label: 'Billing Issue' },
  { value: 'account', label: 'Account Problem' },
  { value: 'feature_request', label: 'Feature Request' },
  { value: 'general', label: 'General Question' },
] as const;

/* ── Auto-diagnostics ─────────────────────────────────────── */

function collectDiagnostics(): Record<string, unknown> {
  if (typeof window === 'undefined') return {};
  return {
    browser: navigator.userAgent,
    platform: navigator.platform,
    language: navigator.language,
    screen: `${screen.width}x${screen.height}`,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    timestamp: new Date().toISOString(),
  };
}

/* ── Page ─────────────────────────────────────────────────── */

export default function SupportPage() {
  const fieldId = useId();
  const { entitlements } = useEntitlements();
  const [issueType, setIssueType] = useState('general');
  const [description, setDescription] = useState('');
  const [includeDiagnostics, setIncludeDiagnostics] = useState(true);

  const { data: tickets } = useQuery<Ticket[]>({
    queryKey: ['support', 'tickets'],
    queryFn: () => apiFetch<Ticket[]>('/support/tickets'),
    staleTime: 30_000,
  });

  const submitTicket = useMutation({
    mutationFn: () =>
      apiFetch<TicketResponse>('/support/ticket', {
        method: 'POST',
        body: JSON.stringify({
          issue_type: issueType,
          description,
          diagnostics: includeDiagnostics ? collectDiagnostics() : undefined,
        }),
      }),
    onSuccess: () => {
      setDescription('');
    },
  });

  return (
    <div>
      <PageHeader title="Support" subtitle="Get help with your LAP account" />

      {/* ── Status ────────────────────────────────── */}
      <div className="bg-concrete rounded-lg border border-steel/20 p-4 mb-6">
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-acid-green" />
          <span className="font-telemetry text-sm text-chalk">All Systems Operational</span>
          <Link
            href="https://status.lap-coach.racing"
            target="_blank"
            className="text-acid-green text-xs font-telemetry hover:underline ml-auto"
          >
            Status Page
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* ── Contact Support ─────────────────────── */}
        <div className="bg-concrete rounded-lg border border-steel/20 p-6">
          <h3 className="font-monument text-sm text-chalk mb-4">Contact Support</h3>

          {submitTicket.isSuccess ? (
            <div className="text-center py-6">
              <p className="text-acid-green font-telemetry text-sm mb-2">
                Ticket #{submitTicket.data.ticket_id} submitted
              </p>
              <p className="text-steel text-xs font-body">
                We&apos;ll respond within 24 hours.
              </p>
              <button
                onClick={() => submitTicket.reset()}
                className="mt-4 text-acid-green text-xs font-telemetry hover:underline"
              >
                Submit another ticket
              </button>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                submitTicket.mutate();
              }}
              className="space-y-4"
            >
              {/* Issue type */}
              <div>
                <label htmlFor={`${fieldId}-issue`} className="block text-steel text-xs font-telemetry mb-1">Issue Type</label>
                <select
                  id={`${fieldId}-issue`}
                  value={issueType}
                  onChange={(e) => setIssueType(e.target.value)}
                  disabled={submitTicket.isPending}
                  className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm focus:border-acid-green/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {ISSUE_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Description */}
              <div>
                <label htmlFor={`${fieldId}-desc`} className="block text-steel text-xs font-telemetry mb-1">Description</label>
                <textarea
                  id={`${fieldId}-desc`}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe your issue..."
                  rows={5}
                  maxLength={5000}
                  disabled={submitTicket.isPending}
                  className="w-full bg-asphalt border border-steel/30 rounded-md px-3 py-2 text-chalk font-body text-sm resize-none focus:border-acid-green/40 focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed"
                />
                <p className="text-steel text-[10px] font-body mt-1 text-right">
                  {description.length}/5000
                </p>
              </div>

              {/* Auto-diagnostics */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeDiagnostics}
                  onChange={(e) => setIncludeDiagnostics(e.target.checked)}
                  disabled={submitTicket.isPending}
                  className="w-4 h-4 rounded accent-acid-green disabled:opacity-60"
                />
                <span className="text-steel text-xs font-body">
                  Include browser diagnostics (browser, OS, screen size)
                </span>
              </label>

              {/* Pre-filled context */}
              <div className="bg-asphalt rounded-md p-3 text-xs">
                <p className="text-steel font-telemetry mb-1">Auto-filled context:</p>
                <p className="text-steel/60 font-body">
                  Plan: {entitlements?.planTier || 'unknown'} &middot;
                  Status: {entitlements?.subscriptionStatus || 'unknown'}
                </p>
              </div>

              {submitTicket.isError && (
                <p className="text-safety-red text-xs font-telemetry">
                  {(submitTicket.error as Error).message}
                </p>
              )}

              <button
                type="submit"
                disabled={!description.trim() || submitTicket.isPending}
                className="w-full bg-gold text-asphalt font-telemetry text-sm py-2.5 rounded-md hover:brightness-110 transition disabled:opacity-50"
              >
                {submitTicket.isPending ? 'Submitting...' : 'Submit Ticket'}
              </button>
            </form>
          )}
        </div>

        {/* ── Right column ────────────────────────── */}
        <div className="space-y-6">
          {/* Documentation links */}
          <div className="bg-concrete rounded-lg border border-steel/20 p-6">
            <h3 className="font-monument text-sm text-chalk mb-4">Documentation</h3>
            <div className="space-y-2">
              <Link
                href="/product"
                className="block text-acid-green text-sm font-telemetry hover:underline"
              >
                Getting Started Guide
              </Link>
              <Link
                href="/product/features"
                className="block text-acid-green text-sm font-telemetry hover:underline"
              >
                Feature Documentation
              </Link>
              <Link
                href="/pricing"
                className="block text-acid-green text-sm font-telemetry hover:underline"
              >
                Plans & Pricing
              </Link>
              <Link
                href="/privacy"
                className="block text-acid-green text-sm font-telemetry hover:underline"
              >
                Privacy Policy
              </Link>
              <Link
                href="/terms"
                className="block text-acid-green text-sm font-telemetry hover:underline"
              >
                Terms of Service
              </Link>
            </div>
          </div>

          {/* Recent tickets */}
          <div className="bg-concrete rounded-lg border border-steel/20 p-6">
            <h3 className="font-monument text-sm text-chalk mb-4">Your Tickets</h3>
            {tickets && tickets.length > 0 ? (
              <div className="space-y-2">
                {tickets.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between bg-asphalt rounded-md p-3"
                  >
                    <div>
                      <p className="text-chalk text-xs font-telemetry">
                        #{t.id} &middot; {t.issue_type}
                      </p>
                      <p className="text-steel text-[10px] font-body mt-0.5">
                        {t.description}
                      </p>
                    </div>
                    <span
                      className={`text-[10px] font-telemetry px-2 py-0.5 rounded-full ${
                        t.status === 'open'
                          ? 'bg-marshal-yellow/20 text-marshal-yellow'
                          : t.status === 'resolved'
                            ? 'bg-acid-green/20 text-acid-green'
                            : 'bg-steel/20 text-steel'
                      }`}
                    >
                      {t.status}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-steel text-sm font-body">No tickets yet</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
