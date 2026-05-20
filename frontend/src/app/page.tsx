"use client";

import Link from "next/link";
import { Cpu, Sparkles, ArrowRight, Database, History } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export default function LandingPage() {
  return (
    <div className="space-y-10 py-4 max-w-3xl mx-auto">
      <div className="text-center space-y-5">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl brand-gradient shadow-[0_4px_14px_0_oklch(0.60_0.175_68_/_0.35)] mx-auto">
          <Cpu className="w-7 h-7 text-white" />
        </div>

        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full bg-primary/8 border border-primary/20 px-4 py-1.5">
            <Sparkles className="w-3 h-3 text-primary" />
            <span className="text-[11px] font-bold text-primary/80 uppercase tracking-widest">
              CNC Costing AI
            </span>
          </div>

          <h1 className="text-[32px] font-bold tracking-tight text-foreground leading-tight">
            AI-Powered Manufacturing<br className="hidden sm:block" /> Cost Estimator
          </h1>

          <p className="text-[14px] text-muted-foreground max-w-md mx-auto leading-relaxed">
            Upload a 2D engineering drawing and a 3D STEP file. Our pipeline returns features, operations, cycle time, and a precise cost estimate.
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Link href="/analyze" className="block">
          <Card className="border-amber-200 hover:border-amber-300 hover:shadow-md transition-all cursor-pointer">
            <CardContent className="p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-amber-50 text-amber-600">
                  <Sparkles className="w-5 h-5" />
                </div>
                <ArrowRight className="w-4 h-4 text-amber-400" />
              </div>
              <div>
                <div className="text-[14px] font-semibold text-foreground">New Analysis</div>
                <div className="text-[12px] text-muted-foreground mt-1">Run a costing analysis on a STEP + PDF.</div>
              </div>
            </CardContent>
          </Card>
        </Link>

        <Link href="/history" className="block">
          <Card className="hover:shadow-md transition-all cursor-pointer">
            <CardContent className="p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-zinc-50 text-zinc-600">
                  <History className="w-5 h-5" />
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400" />
              </div>
              <div>
                <div className="text-[14px] font-semibold text-foreground">History</div>
                <div className="text-[12px] text-muted-foreground mt-1">Past analyses and saved results.</div>
              </div>
            </CardContent>
          </Card>
        </Link>

        <Link href="/cost-db" className="block">
          <Card className="hover:shadow-md transition-all cursor-pointer">
            <CardContent className="p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-zinc-50 text-zinc-600">
                  <Database className="w-5 h-5" />
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400" />
              </div>
              <div>
                <div className="text-[14px] font-semibold text-foreground">Cost Database</div>
                <div className="text-[12px] text-muted-foreground mt-1">Labor rates, machines, tooling, stock.</div>
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>

      <p className="text-center text-[11.5px] text-muted-foreground/50 pb-2">
        Single deterministic OCC pipeline with VLM-based 2D drawing extraction.
      </p>
    </div>
  );
}
