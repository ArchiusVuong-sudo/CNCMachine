"use client";

import { useEffect, useState, Suspense } from "react";
import { useParams } from "next/navigation";
import { A4DetailView } from "./a4-detail";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { FinalAnswer } from "@/lib/api/types";

function AnalysisDetailRouter({ id }: { id: string }) {
  const [result, setResult] = useState<FinalAnswer | Record<string, unknown> | null>(null);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.getAnalysis(id)
      .then((r) => { if (!cancelled) setResult(r); })
      .catch((e) => {
        if (cancelled) return;
        const msg = e instanceof ApiError
          ? (e.status === 404 ? null : e.message)
          : e instanceof Error ? e.message : String(e);
        setError(msg);
      })
      .finally(() => { if (!cancelled) setChecked(true); });
    return () => { cancelled = true; };
  }, [id]);

  if (!checked) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-amber-400/60" />
      </div>
    );
  }

  if (result) {
    return (
      <Suspense fallback={<div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-amber-400/60" /></div>}>
        <A4DetailView result={result} analysisId={id} />
      </Suspense>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <p className="text-sm text-muted-foreground">
        {error ?? "Analysis not found."}
      </p>
    </div>
  );
}

export default function AnalysisDetailPage() {
  const params = useParams();
  const id = params.id as string;
  return <AnalysisDetailRouter id={id} />;
}
