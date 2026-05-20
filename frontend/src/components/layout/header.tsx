"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { LayoutDashboard, History, Menu, Cpu } from "lucide-react";
import { useState } from "react";

const navItems = [
  { href: "/",         label: "Home",          icon: LayoutDashboard },
  { href: "/analyze",  label: "New Analysis",  icon: History         },
  { href: "/history",  label: "History",       icon: History         },
];

const PAGE_TITLES: Record<string, string> = {
  "/":        "Home",
  "/analyze": "Analysis",
  "/history": "Analysis History",
};

export function Header() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const title = PAGE_TITLES[pathname] ?? (pathname.startsWith("/analysis/") ? "Analysis Results" : "");

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/90 backdrop-blur-sm h-[60px] shadow-[0_1px_4px_0_rgb(0,0,0,0.04)]">
      <div className="flex items-center h-full px-5 lg:px-6 gap-4">

        {/* Mobile brand */}
        <div className="flex items-center gap-2.5 lg:hidden">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setMobileOpen(!mobileOpen)}>
            <Menu className="w-4 h-4" />
          </Button>
          <div className="flex items-center justify-center w-7 h-7 rounded-md brand-gradient shrink-0">
            <Cpu className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="font-semibold text-sm">CNC Costing AI</span>
        </div>

        {/* Desktop: page title */}
        <div className="hidden lg:block">
          <span className="text-[13px] font-semibold text-foreground/80">{title}</span>
        </div>

        <div className="flex-1" />

        {/* Online status pill */}
        <div className="hidden sm:flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-3 py-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 status-online" />
          <span>online</span>
        </div>
      </div>

      {/* Mobile nav */}
      {mobileOpen && (
        <nav className="lg:hidden border-t border-border px-3 py-2 space-y-0.5 bg-sidebar">
          {navItems.map((item) => {
            const isActive = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className={cn(
                  "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  isActive
                    ? "text-primary bg-primary/10"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
                )}
              >
                <item.icon className="w-3.5 h-3.5" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      )}
    </header>
  );
}
