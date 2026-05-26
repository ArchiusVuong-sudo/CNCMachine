import Link from "next/link";
import { ArrowLeft, Database } from "lucide-react";
import { BrandMark } from "@/components/layout/brand-mark";

export default function CostDbLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-muted/30">
      <header className="sticky top-0 z-30 h-14 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-full max-w-6xl items-center gap-4 px-4 sm:px-6">
          <BrandMark />
          <span className="hidden h-5 w-px bg-border sm:block" />
          <div className="hidden items-center gap-2 text-sm font-medium text-muted-foreground sm:flex">
            <Database className="h-4 w-4" />
            Cost Database
          </div>
          <Link
            href="/"
            className="ml-auto inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Studio
          </Link>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}
