"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { LayoutDashboard, History, Cpu, Sparkles, Database } from "lucide-react";
import { useEffect, useState } from "react";

type HealthState = "loading" | "ok" | "error";

function ServerStatus() {
  const [health, setHealth] = useState<HealthState>("loading");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await fetch("/api/v1/health", { cache: "no-store" });
        if (!cancelled) setHealth(res.ok ? "ok" : "error");
      } catch {
        if (!cancelled) setHealth("error");
      }
    }

    check();
    const id = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const label  = health === "ok" ? "Pipeline Ready" : health === "error" ? "Pipeline Offline" : "Checking…";
  const colors =
    health === "ok"
      ? { wrap: "bg-emerald-50 border-emerald-100", dot: "bg-emerald-500", title: "text-emerald-700", sub: "text-emerald-600/60" }
      : health === "error"
      ? { wrap: "bg-red-50 border-red-100",         dot: "bg-red-500",     title: "text-red-700",     sub: "text-red-600/60"     }
      : { wrap: "bg-zinc-50 border-zinc-200",        dot: "bg-zinc-400",    title: "text-zinc-600",    sub: "text-zinc-500/60"    };

  return (
    <div className={cn("flex items-center gap-2.5 rounded-lg border px-3 py-2.5", colors.wrap)}>
      <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", colors.dot, health === "ok" && "status-online")} />
      <div className="flex-1 min-w-0">
        <div className={cn("text-[11px] font-semibold", colors.title)}>{label}</div>
        <div className={cn("text-[10px] font-mono truncate", colors.sub)}>Qwen3-VL · vLLM</div>
      </div>
    </div>
  );
}

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
}

interface NavSection {
  heading?: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    items: [
      { href: "/",           label: "Home",          icon: LayoutDashboard },
      { href: "/analyze",    label: "New Analysis",  icon: Sparkles },
      { href: "/history",    label: "History",       icon: History },
      { href: "/cost-db",    label: "Cost Database", icon: Database },
    ],
  },
];

function SidebarNav() {
  const pathname = usePathname();

  function isItemActive(item: NavItem): boolean {
    if (item.href === "/") return pathname === "/";
    return pathname.startsWith(item.href);
  }

  return (
    <nav className="flex-1 px-3 py-4 space-y-4 overflow-y-auto">
      {navSections.map((section, si) => (
        <div key={si} className="space-y-0.5">
          {section.heading && (
            <p className="px-2.5 pb-1.5 pt-0.5 text-[9.5px] font-bold uppercase tracking-widest text-amber-500/70">
              {section.heading}
            </p>
          )}
          {section.items.map((item) => {
            const active = isItemActive(item);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-2.5 py-2.5 rounded-lg text-[13px] font-medium transition-all",
                  active
                    ? "bg-primary/8 text-primary"
                    : "text-muted-foreground/65 hover:text-foreground hover:bg-accent/60",
                )}
              >
                <div className={cn(
                  "flex items-center justify-center w-7 h-7 rounded-md shrink-0 transition-colors",
                  active
                    ? "bg-primary/15 text-primary"
                    : "bg-muted/70 text-muted-foreground",
                )}>
                  <item.icon className="w-3.5 h-3.5" />
                </div>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden lg:flex lg:flex-col lg:w-60 border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="flex items-center gap-3 px-5 h-[60px] border-b border-sidebar-border">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg brand-gradient shrink-0">
          <Cpu className="w-4 h-4 text-white" />
        </div>
        <div className="leading-none min-w-0">
          <div className="text-[13.5px] font-semibold tracking-tight">CNC Costing AI</div>
          <div className="text-[10px] text-sidebar-foreground/40 mt-0.5 font-mono">v4.1</div>
        </div>
      </div>

      <SidebarNav />

      {/* Status footer — live health poll */}
      <div className="px-3 pb-4 border-t border-sidebar-border pt-3">
        <ServerStatus />
      </div>
    </aside>
  );
}
