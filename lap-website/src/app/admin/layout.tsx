"use client";

import { type ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { QueryProvider } from "@/providers/query-provider";
import { getUserProfile } from "@/lib/auth-store";

const adminNav = [
  { href: "/admin", label: "Dashboard", icon: "◉" },
  { href: "/admin/overview", label: "Overview", icon: "▦" },
  { href: "/admin/analytics", label: "Analytics", icon: "◈" },
  { href: "/admin/users", label: "Users", icon: "◎" },
  { href: "/admin/audit", label: "Audit Log", icon: "☰" },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    const user = getUserProfile();
    if (!user?.is_superadmin) {
      router.replace('/app/sessions');
      return;
    }
    setAllowed(true);
  }, [router]);

  if (!allowed) {
    return <div className="flex min-h-screen items-center justify-center bg-asphalt text-steel font-body text-sm">Access denied</div>;
  }

  return (
    <QueryProvider>
      <div className="flex min-h-screen bg-asphalt text-chalk">
        {/* Sidebar */}
        <aside className="w-56 shrink-0 border-r border-steel/10 bg-concrete p-4">
          <div className="mb-6">
            <Link href="/admin" className="text-lg font-monument text-chalk">
              LAP Admin
            </Link>
            <p className="mt-1 text-xs font-body text-steel/70">Platform Backoffice</p>
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
                  className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
                    active
                      ? "border-acid-green/30 bg-acid-green/10 text-acid-green"
                      : "border-transparent text-steel hover:border-steel/20 hover:bg-white/[0.03] hover:text-chalk"
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
              className="text-xs font-body text-steel/70 transition-colors hover:text-chalk"
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
