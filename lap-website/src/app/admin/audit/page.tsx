"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-client";

type AuditEntry = {
  id: number;
  user_id: number | null;
  action: string;
  details: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string | null;
};

export default function AdminAuditPage() {
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const { data, isLoading } = useQuery({
    queryKey: ["admin-audit", action, userId, offset],
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      if (action) params.set("action", action);
      if (userId) params.set("user_id", userId);
      return await apiFetch<{ entries: AuditEntry[] }>(`/admin/audit-log?${params}`);
    },
  });

  const entries = data?.entries ?? [];

  function parseDetails(raw: string | null): string {
    if (!raw) return "—";
    try {
      const obj = typeof raw === "string" ? JSON.parse(raw) : raw;
      return JSON.stringify(obj, null, 0).slice(0, 120);
    } catch {
      return String(raw).slice(0, 120);
    }
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-6 text-2xl font-bold text-white">Audit Log</h1>

      <div className="mb-4 flex gap-3">
        <input
          type="text"
          placeholder="Filter by action..."
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setOffset(0);
          }}
          className="w-48 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/30 outline-none focus:border-acid-green/50 focus:ring-1 focus:ring-acid-green/20"
        />
        <input
          type="text"
          placeholder="User ID..."
          value={userId}
          onChange={(e) => {
            setUserId(e.target.value);
            setOffset(0);
          }}
          className="w-32 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/30 outline-none focus:border-acid-green/50 focus:ring-1 focus:ring-acid-green/20"
        />
      </div>

      {isLoading ? (
        <div className="p-12 text-center text-white/40">Loading...</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-white/10">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/10 bg-white/5 text-left text-xs text-white/40">
                <th className="px-4 py-3 font-medium">Time</th>
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Action</th>
                <th className="px-4 py-3 font-medium">Details</th>
                <th className="px-4 py-3 font-medium">IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {entries.map((entry) => (
                <tr key={entry.id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-3 text-xs text-white/40">
                    {entry.created_at
                      ? new Date(entry.created_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-sm text-white/60">
                    {entry.user_id ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-white">
                      {entry.action}
                    </span>
                  </td>
                  <td className="max-w-xs truncate px-4 py-3 text-xs text-white/40">
                    {parseDetails(entry.details)}
                  </td>
                  <td className="px-4 py-3 text-xs text-white/30">
                    {entry.ip_address ?? "—"}
                  </td>
                </tr>
              ))}
              {entries.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-white/40"
                  >
                    No audit entries found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setOffset(Math.max(0, offset - limit))}
          disabled={offset === 0}
          className="rounded px-3 py-1 text-sm text-white/50 hover:text-white disabled:opacity-30"
        >
          Previous
        </button>
        <span className="text-sm text-white/40">
          Showing {offset + 1}–{offset + entries.length}
        </span>
        <button
          type="button"
          onClick={() => setOffset(offset + limit)}
          disabled={entries.length < limit}
          className="rounded px-3 py-1 text-sm text-white/50 hover:text-white disabled:opacity-30"
        >
          Next
        </button>
      </div>
    </div>
  );
}
