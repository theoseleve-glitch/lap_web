"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-client";

type User = {
  id: number;
  email: string;
  display_name: string | null;
  plan_tier: string | null;
  subscription_status: string | null;
  created_at: string | null;
  email_verified: boolean | null;
  suspended_at: string | null;
  is_platform_admin: boolean;
};

export default function AdminUsersPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const { data, isLoading } = useQuery({
    queryKey: ["admin-users", search, offset],
    queryFn: async () => {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (search) params.set("search", search);
      return await apiFetch<{ users: User[]; total: number }>(`/admin/users?${params}`);
    },
  });

  const suspendMut = useMutation({
    mutationFn: async ({ userId, reason }: { userId: number; reason: string }) => {
      await apiFetch(`/admin/users/${userId}/suspend`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const unsuspendMut = useMutation({
    mutationFn: async (userId: number) => {
      await apiFetch(`/admin/users/${userId}/unsuspend`, {
        method: "POST",
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  const users = data?.users ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Users</h1>
        <span className="text-sm text-white/40">{total} total</span>
      </div>

      <div className="mb-4">
        <input
          type="text"
          placeholder="Search by email or name..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
          className="w-full max-w-sm rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-white/30 outline-none focus:border-[#B6FF2E]/50"
        />
      </div>

      {isLoading ? (
        <div className="p-12 text-center text-white/40">Loading...</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-white/10">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/10 bg-white/5 text-left text-xs text-white/40">
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Plan</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Joined</th>
                <th className="px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-3">
                    <div className="text-sm text-white">
                      {user.display_name ?? user.email}
                    </div>
                    <div className="text-xs text-white/30">{user.email}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-white/60">
                    {user.plan_tier ?? "demo"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs ${
                        user.suspended_at
                          ? "bg-red-500/20 text-red-400"
                          : user.subscription_status === "active"
                            ? "bg-green-500/20 text-green-400"
                            : "bg-white/10 text-white/50"
                      }`}
                    >
                      {user.suspended_at
                        ? "Suspended"
                        : user.subscription_status ?? "free"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-white/40">
                    {user.created_at
                      ? new Date(user.created_at).toLocaleDateString()
                      : "—"}
                  </td>
                  <td className="px-4 py-3">
                    {user.suspended_at ? (
                      <button
                        onClick={() => unsuspendMut.mutate(user.id)}
                        disabled={unsuspendMut.isPending}
                        className="rounded px-2 py-1 text-xs text-green-400 hover:bg-green-500/10 disabled:opacity-50"
                      >
                        Unsuspend
                      </button>
                    ) : (
                      <button
                        onClick={() => {
                          const reason = prompt("Suspension reason:");
                          if (reason)
                            suspendMut.mutate({ userId: user.id, reason });
                        }}
                        disabled={suspendMut.isPending}
                        className="rounded px-2 py-1 text-xs text-red-400 hover:bg-red-500/10 disabled:opacity-50"
                      >
                        Suspend
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > limit && (
        <div className="mt-4 flex items-center justify-between">
          <button
            onClick={() => setOffset(Math.max(0, offset - limit))}
            disabled={offset === 0}
            className="rounded px-3 py-1 text-sm text-white/50 hover:text-white disabled:opacity-30"
          >
            Previous
          </button>
          <span className="text-sm text-white/40">
            {offset + 1}–{Math.min(offset + limit, total)} of {total}
          </span>
          <button
            onClick={() => setOffset(offset + limit)}
            disabled={offset + limit >= total}
            className="rounded px-3 py-1 text-sm text-white/50 hover:text-white disabled:opacity-30"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
