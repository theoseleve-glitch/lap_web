"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { QueryProvider } from "@/providers/query-provider";

const adminNav = [
  { href: "/admin", label: "Dashboard", icon: "◉" },
  { href: "/admin/users", label: "Users", icon: "◎" },
  { href: "/admin/audit", label: "Audit Log", icon: "☰" },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <QueryProvider>
      <div className="flex min-h-screen bg-[#0B0C0F]">
        {/* Sidebar */}
        <aside className="w-56 shrink-0 border-r border-white/10 bg-[#0B0C0F] p-4">
          <div className="mb-6">
            <Link href="/admin" className="text-lg font-bold text-white">
              LAP Admin
            </Link>
            <p className="mt-1 text-xs text-white/30">Platform Backoffice</p>
          </div>
          <nav className="space-y-1">
            {adminNav.map((item) => {
              const active =
                item.href === "/admin"
                  ? pathname === "/admin"
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm ${
                    active
                      ? "bg-white/10 text-white"
                      : "text-white/50 hover:bg-white/5 hover:text-white/80"
                  }`}
                >
                  <span className="w-4 text-center">{item.icon}</span>
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="mt-8 border-t border-white/10 pt-4">
            <Link
              href="/app/dashboard"
              className="text-xs text-white/30 hover:text-white/50"
            >
              ← Back to App
            </Link>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </QueryProvider>
  );
}
