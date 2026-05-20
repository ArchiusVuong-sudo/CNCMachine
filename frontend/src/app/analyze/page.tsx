"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FileUpload } from "@/components/ui/FileUpload";
import { AgentStream } from "@/components/agent/agent-stream";
import { LiveCanvas } from "@/components/a4/live-canvas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useApproach4 } from "@/lib/hooks/useApproach4";
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  X,
  Plus,
  Bot,
  Eye,
  Layers,
  Wrench,
  DollarSign,
  Sparkles,
  GitMerge,
  PackageOpen,
} from "lucide-react";

/* eslint-disable @typescript-eslint/no-explicit-any */

// A4 pipeline step metadata. `match` lets a step consume several tool events
// (e.g. the per-component `process_component_*` stream).
type StepMatch = (completed: Set<string>, active: string | null) => { done: boolean; active: boolean };
interface PipelineStep {
  icon: typeof Eye;
  label: string;
  match: StepMatch;
}
const exactMatch = (tool: string): StepMatch =>
  (completed, active) => ({ done: completed.has(tool), active: active === tool });
const prefixMatch = (prefix: string): StepMatch =>
  (completed, active) => {
    const anyCompleted = Array.from(completed).some((t) => t.startsWith(prefix));
    const isActive     = active?.startsWith(prefix) ?? false;
    return { done: anyCompleted && !isActive, active: isActive };
  };

const PIPELINE_STEPS: PipelineStep[] = [
  { icon: Eye,        label: "2D Extract",  match: exactMatch("analyze_drawing")        },
  { icon: Layers,     label: "3D Assembly", match: exactMatch("analyze_step_assembly")  },
  { icon: GitMerge,   label: "BOM Map",     match: exactMatch("map_bom_to_components")  },
  { icon: Wrench,     label: "Components",  match: prefixMatch("process_component_")    },
  { icon: DollarSign, label: "Cost",        match: exactMatch("estimate_cost")          },
];

// ---------------------------------------------------------------------------
// Upload view
// ---------------------------------------------------------------------------

function UploadView({
  file3d,
  file2d,
  loading,
  error,
  onFile3dChange,
  onFile2dChange,
  onAnalyze,
  onBack,
  batchSize,
  onBatchSizeChange,
  assemblyPartType,
  onAssemblyPartTypeChange,
}: {
  file3d: File | null;
  file2d: File | null;
  loading: boolean;
  error: string | null;
  onFile3dChange: (f: File | null) => void;
  onFile2dChange: (f: File | null) => void;
  onAnalyze: () => void;
  onBack: () => void;
  batchSize: number;
  onBatchSizeChange: (n: number) => void;
  assemblyPartType: string | null;
  onAssemblyPartTypeChange: (v: string | null) => void;
}) {
  const [file3dError, setFile3dError] = useState<string | null>(null);
  const [file2dError, setFile2dError] = useState<string | null>(null);

  const handleFile3dChange = (f: File | null) => { setFile3dError(null); onFile3dChange(f); };
  const handleFile2dChange = (f: File | null) => { setFile2dError(null); onFile2dChange(f); };

  return (
    <div className="space-y-8 py-2 max-w-2xl mx-auto">
      {/* Back + badge */}
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" className="gap-1.5 -ml-1 text-muted-foreground" onClick={onBack}>
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </Button>
        <div className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 border text-[11px] font-semibold uppercase tracking-wider bg-amber-50 border-amber-200/60 text-amber-700">
          <Sparkles className="w-3 h-3" />
          CNC Costing
        </div>
      </div>

      {/* Heading */}
      <div className="text-center space-y-2">
        <h1 className="text-[28px] font-bold tracking-tight leading-tight">Refined Algorithm — XDE + FreeCAD Path + gcodeEstimator</h1>
        <p className="text-[13.5px] text-muted-foreground max-w-md mx-auto leading-relaxed">
          Multi-component assembly decomposition, rule-based feature recognition with FACE_IDs, real G-code cycle time simulation, user-owned cost database.
        </p>
      </div>

      {/* Upload card */}
      <Card className="shadow-[0_2px_12px_0_rgb(0,0,0,0.06)] border-border/80">
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Upload Files</CardTitle>
          <CardDescription className="text-[13px]">
            Both files are required. The STEP file provides 3D geometry; the drawing provides GD&amp;T, tolerances, and material specification.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <FileUpload
            file3d={file3d}
            file2d={file2d}
            onFile3dChange={handleFile3dChange}
            onFile2dChange={handleFile2dChange}
            error3d={file3dError ?? undefined}
            error2d={file2dError ?? undefined}
            onReject3d={setFile3dError}
            onReject2d={setFile2dError}
          />

          {/* Assembly part-type override */}
          <div className="space-y-1.5">
            <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              Part Category
              <span className="ml-1.5 font-normal normal-case text-muted-foreground/50">
                (override the auto-classifier)
              </span>
            </div>
            <select
              value={assemblyPartType ?? ""}
              onChange={(e) => onAssemblyPartTypeChange(e.target.value || null)}
              className="w-full rounded-lg border border-amber-200 bg-amber-50/30 px-3 py-2 text-[13px] text-amber-900 focus:outline-none focus:ring-2 focus:ring-amber-400/40"
            >
              <option value="">Auto-detect (use 3D classifier)</option>
              <option value="cnc_milling">CNC Milling — 3/4/5-axis</option>
              <option value="cnc_lathe">CNC Lathe — turned parts</option>
              <option value="cnc_lathe_milling">CNC Mill-Turn</option>
              <option value="cnc_router">CNC Router — composites / wood</option>
              <option value="sheet_metal">Sheet Metal — laser / brake</option>
              <option value="tube_pipe">Tube / Pipe</option>
              <option value="hardware">Standard Hardware</option>
            </select>
            <p className="text-[11px] text-muted-foreground/70 px-1">
              Applied to every component in the assembly. The reconciler may still
              downgrade individual parts (e.g. silicone gaskets → hardware).
            </p>
          </div>

          {/* Batch size */}
          <div className="space-y-1.5">
            <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              Batch Size
              <span className="ml-1.5 font-normal normal-case text-muted-foreground/50">
                (pieces per production run)
              </span>
            </div>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min={1}
                max={10000}
                value={batchSize}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  if (!isNaN(v) && v >= 1) onBatchSizeChange(v);
                }}
                className="w-28 rounded-lg border border-amber-200 bg-amber-50/50 px-3 py-1.5 text-[13px] font-mono text-amber-800 focus:outline-none focus:ring-2 focus:ring-amber-400/40"
              />
              <div className="flex gap-1.5">
                {[1, 10, 50, 100, 500].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => onBatchSizeChange(n)}
                    className={`text-[11px] rounded-md px-2.5 py-1 border font-mono transition-colors ${
                      batchSize === n
                        ? "bg-amber-500 text-white border-amber-500"
                        : "border-amber-200 text-amber-600 hover:bg-amber-50"
                    }`}
                  >
                    ×{n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 rounded-xl p-3.5 text-[13px] leading-snug">
              {error}
            </div>
          )}

          <Button
            onClick={onAnalyze}
            disabled={loading || !file2d || !file3d || !!file3dError || !!file2dError}
            className="w-full h-12 text-[14px] font-semibold rounded-xl shadow-[0_1px_3px_0_rgb(0,0,0,0.12)] hover:shadow-[0_3px_8px_0_rgb(0,0,0,0.15)] transition-shadow"
            size="lg"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Uploading…
              </>
            ) : (
              <>
                <Bot className="w-4 h-4" />
                Start Analysis
              </>
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stream view (live pipeline activity + Live Canvas)
// ---------------------------------------------------------------------------

function StreamView({
  hook,
  file3d,
  file2d,
  onNewAnalysis,
}: {
  hook: ReturnType<typeof useApproach4>;
  file3d: File | null;
  file2d: File | null;
  onNewAnalysis: () => void;
}) {
  const router = useRouter();
  const { status, messages, liveThinking, completedTools, activeTool, results, cancel, analysisId } = hook;
  const isStreaming = status === "streaming";
  const isDone      = status === "done";
  const hasError    = status === "error";
  const batchSize   = results?.batch_size ?? hook.batchSize ?? 1;
  const compCount   = results?.assembly_data?.component_count ?? results?.components?.length ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold tracking-tight">
              {isDone ? "Assembly Analysis Complete" : hasError && !isStreaming ? "Analysis Failed" : "Running Analysis"}
            </h2>
            <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider bg-amber-100 text-amber-700 border border-amber-200/60 rounded-full px-2.5 py-1">
              <Sparkles className="w-2.5 h-2.5" />
              CNC
            </span>
          </div>
          <p className="text-[12.5px] text-muted-foreground mt-0.5 font-mono truncate max-w-sm">
            {[file3d?.name, file2d?.name].filter(Boolean).join(" + ") || "Processing…"}
          </p>
          {isDone && compCount > 0 && (
            <div className="flex items-center gap-3 mt-1.5">
              <Badge variant="secondary" className="border-amber-300/40 bg-amber-50 text-amber-700 text-[10px]">
                <PackageOpen className="w-2.5 h-2.5 mr-1" />
                {compCount} component{compCount !== 1 ? "s" : ""}
              </Badge>
              {batchSize > 1 && (
                <Badge variant="secondary" className="border-amber-300/40 bg-amber-50 text-amber-700 text-[10px]">
                  batch ×{batchSize}
                </Badge>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isStreaming && (
            <Button variant="destructive" size="sm" className="rounded-lg" onClick={cancel}>
              <X className="w-3.5 h-3.5" />
              Stop
            </Button>
          )}
          {isDone && analysisId && (
            <Button
              size="sm"
              className="rounded-lg bg-amber-500 hover:bg-amber-600 text-white border-amber-600"
              onClick={() => router.push(`/analysis/${analysisId}`)}
            >
              View Details
              <ArrowRight className="w-3.5 h-3.5" />
            </Button>
          )}
          {(isDone || (hasError && !isStreaming)) && (
            <Button variant="outline" size="sm" className="rounded-lg" onClick={onNewAnalysis}>
              <Plus className="w-3.5 h-3.5" />
              New Analysis
            </Button>
          )}
        </div>
      </div>

      {/* Pipeline step pills */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {PIPELINE_STEPS.map((step, i) => {
          const { done: isDoneStep, active: isActiveTool } = step.match(completedTools, activeTool);
          return (
            <div key={step.label} className="flex items-center gap-1.5">
              <div className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 border text-[11px] font-semibold transition-all ${
                isDoneStep
                  ? "bg-amber-50 border-amber-200 text-amber-700"
                  : isActiveTool
                  ? "bg-amber-500/10 border-amber-400/40 text-amber-600 animate-pulse"
                  : "bg-card border-border text-muted-foreground/50"
              }`}>
                <step.icon className="w-3 h-3" />
                <span>{step.label}</span>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <ArrowRight className="w-2.5 h-2.5 text-muted-foreground/20" />
              )}
            </div>
          );
        })}
      </div>

      <Separator />

      {/* Activity + Live Canvas split */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        {/* Activity feed — narrower column */}
        <div className="xl:col-span-4 min-w-0">
          <Card className="py-0 overflow-hidden border-amber-200/40 rounded-xl shadow-[0_2px_8px_0_rgb(0,0,0,0.05)] xl:sticky xl:top-4">
            <div className="flex items-center gap-2.5 px-4 py-3 border-b border-amber-100 bg-amber-50/40">
              <div className="flex items-center justify-center w-6 h-6 rounded-md bg-amber-100">
                <Sparkles className="w-3.5 h-3.5 text-amber-600" />
              </div>
              <span className="text-[13px] font-semibold flex-1">Pipeline Activity</span>
              {isStreaming && (
                <Badge variant="info" className="text-[10px] rounded-full px-2.5">Live</Badge>
              )}
            </div>
            <div className="h-[640px]">
              <AgentStream
                messages={messages}
                liveThinking={liveThinking}
                isStreaming={isStreaming}
              />
            </div>
          </Card>
        </div>

        {/* Live Insights Canvas — wider column */}
        <div className="xl:col-span-8 min-w-0 space-y-3">
          <LiveCanvas
            components={hook.canvasComponents}
            isStreaming={isStreaming}
            isDone={isDone}
            totalUsd={hook.totalUsd}
            totalMinutes={hook.totalMinutes}
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AnalyzePage() {
  const router = useRouter();

  const [file3d, setFile3d] = useState<File | null>(null);
  const [file2d, setFile2d] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  // Batch size — persisted to localStorage
  const [batchSize, setBatchSize] = useState<number>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("cncapp:a4:last_batch_size");
      return saved ? parseInt(saved) || 1 : 1;
    }
    return 1;
  });
  const handleBatchSizeChange = (n: number) => {
    setBatchSize(n);
    if (typeof window !== "undefined") {
      localStorage.setItem("cncapp:a4:last_batch_size", String(n));
    }
  };

  // Assembly part-type override — null = auto-detect (classifier rules)
  const [assemblyPartType, setAssemblyPartType] = useState<string | null>(null);

  const hook = useApproach4();

  const isActive = hook.status !== "idle";

  const handleAnalyze = () => {
    if (!file3d && !file2d) {
      setLocalError("Both a 3D STEP/STP file and a 2D engineering drawing are required.");
      return;
    }
    if (!file3d) {
      setLocalError("A 3D STEP or STP file is required.");
      return;
    }
    if (!file2d) {
      setLocalError("A 2D engineering drawing (PDF, PNG, JPG, or TIFF) is required.");
      return;
    }
    setLocalError(null);
    hook.run(file3d, file2d, batchSize, assemblyPartType);
  };

  const handleReset = () => {
    setShowConfirm(false);
    hook.reset();
    setFile3d(null);
    setFile2d(null);
    setLocalError(null);
  };

  const hasResults = hook.isDone && !!hook.results;

  const handleNewAnalysis = () => {
    if (hasResults) {
      setShowConfirm(true);
    } else {
      handleReset();
    }
  };

  const handleBack = () => {
    handleReset();
    router.push("/");
  };

  const loading = hook.status === "uploading";
  const error   = hook.error || localError;

  if (!isActive) {
    return (
      <UploadView
        file3d={file3d}
        file2d={file2d}
        loading={loading}
        error={error}
        onFile3dChange={setFile3d}
        onFile2dChange={setFile2d}
        onAnalyze={handleAnalyze}
        onBack={handleBack}
        batchSize={batchSize}
        onBatchSizeChange={handleBatchSizeChange}
        assemblyPartType={assemblyPartType}
        onAssemblyPartTypeChange={setAssemblyPartType}
      />
    );
  }

  const confirmOverlay = showConfirm && (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-background border border-border rounded-2xl shadow-2xl p-7 max-w-sm w-full mx-4 space-y-5">
        <div className="space-y-1.5">
          <h3 className="text-[16px] font-bold tracking-tight">Start new analysis?</h3>
          <p className="text-[13px] text-muted-foreground leading-relaxed">
            Your current results will be lost. The analysis has been saved to History and can be accessed there.
          </p>
        </div>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="outline" size="sm" className="rounded-lg" onClick={() => setShowConfirm(false)}>
            Cancel
          </Button>
          <Button size="sm" className="rounded-lg" onClick={handleReset}>
            <Plus className="w-3.5 h-3.5" />
            New Analysis
          </Button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {confirmOverlay}
      <StreamView
        hook={hook}
        file3d={file3d}
        file2d={file2d}
        onNewAnalysis={handleNewAnalysis}
      />
    </>
  );
}
