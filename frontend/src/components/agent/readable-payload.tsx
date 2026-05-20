"use client";

/**
 * Shared readable-payload renderer used by the activity feed (`ToolExecution`)
 * and the live-canvas agent timeline (`AgentTimeline`). The goal is to keep
 * users out of raw `{ "foo": "bar" }` braces — top-level scalars render as a
 * label/value grid, nested objects/arrays render as collapsible `<details>`.
 */

const KEY_LABELS: Record<string, string> = {
  feature_count:        "Features",
  dimension_count:      "Dimensions",
  gdt_count:            "GD&T callouts",
  bom_items:            "BOM items",
  material:             "Material",
  part_number:          "Part #",
  part_type:            "Part type",
  component_count:      "Components",
  total_volume_mm3:     "Total volume",
  pmi_available:        "PMI present",
  error:                "Error",
  contact_count:        "Contacts found",
  matched:              "Matched",
  total_components:     "Total components",
  unmatched_bom:        "Unmatched BOM",
  operation_count:      "Operations",
  operations:           "Operations",
  total_minutes:        "Total cycle",
  total_usd:            "Total cost",
  cycle_time_min:       "Cycle time",
  cost_usd:             "Cost",
  total_cycle_time_min: "Total cycle",
  total_setup_time_min: "Total setup",
  total_cost_usd:       "Total cost",
  recommended_machine:  "Recommended machine",
  material_notes:       "Material notes",
  component_index:      "Component idx",
  fallback_used:        "Fallback used",
  rationale:            "Rationale",
  kb_hits_seen:         "KB hits seen",
  raw_material_usd:     "Raw material",
  setup_usd:            "Setup",
  machining_total_usd:  "Machining",
  deburr_usd:           "Deburring",
  inspection_usd:       "Inspection",
  labor_usd:            "Labor",
  machine_usd:          "Machine",
  overhead_usd:         "Overhead",
  machine_assignments:  "Machine assignments",
  tool_assignments:     "Tool assignments",
  candidate_count:      "Candidates",
  candidate_machines:   "Candidate machines",
  candidate_tools:      "Candidate tools",
  stock_id:             "Stock ID",
  shape:                "Shape",
  dimensions_mm:        "Dimensions",
  mass_g:               "Mass",
  rollup:               "Roll-up",
};

export function humanLabel(key: string): string {
  if (KEY_LABELS[key]) return KEY_LABELS[key];
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatValue(key: string, val: unknown): string {
  if (val === null || val === undefined) return "—";
  if (typeof val === "boolean")           return val ? "Yes" : "No";
  if (typeof val === "number") {
    if (key.endsWith("_mm3") && val >= 1000) return `${(val / 1000).toFixed(1)} cm³`;
    if (key.endsWith("_mm"))                 return `${val.toFixed(2)} mm`;
    if (key === "mass_g" && val >= 1000)     return `${(val / 1000).toFixed(2)} kg`;
    if (key === "mass_g")                    return `${val.toFixed(1)} g`;
    if (key.endsWith("_usd") || key === "total_usd" || key === "cost_usd" || key === "total_cost_usd")
      return `$${val.toFixed(2)}`;
    if (key.endsWith("_min") || key === "total_minutes")
      return `${val.toFixed(1)} min`;
    if (key.endsWith("_per_hr"))
      return `$${val.toFixed(0)}/hr`;
    if (key === "elapsed_ms")
      return val < 1000 ? `${val} ms` : `${(val / 1000).toFixed(2)} s`;
    return Number.isInteger(val) ? `${val}` : val.toFixed(3);
  }
  if (typeof val === "string") return val || "—";
  return JSON.stringify(val);
}

export interface ReadablePayloadProps {
  payload:    Record<string, unknown>;
  /** Optional emphasis: scalar keys listed here render first, in bold. */
  highlight?: string[];
  /** Empty-state copy. Defaults to "No data." */
  emptyText?: string;
}

export function ReadablePayload({ payload, highlight, emptyText = "No data." }: ReadablePayloadProps) {
  const entries = Object.entries(payload);
  if (entries.length === 0) {
    return <div className="text-[11px] text-current/50 italic">{emptyText}</div>;
  }

  // Split top-level into scalars vs. nested objects/arrays.
  const scalars: [string, unknown][] = [];
  const nested:  [string, unknown][] = [];
  for (const [k, v] of entries) {
    if (v && typeof v === "object") nested.push([k, v]);
    else scalars.push([k, v]);
  }

  // Sort scalars so highlighted keys come first (in the order requested).
  if (highlight && highlight.length > 0) {
    const rank = new Map(highlight.map((k, i) => [k, i]));
    scalars.sort(([a], [b]) => {
      const ra = rank.has(a) ? rank.get(a)! : 1_000;
      const rb = rank.has(b) ? rank.get(b)! : 1_000;
      return ra - rb;
    });
  }

  return (
    <div className="space-y-1.5">
      {scalars.length > 0 && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-[11px] bg-muted/60 rounded p-2">
          {scalars.map(([k, v]) => {
            const formatted = formatValue(k, v);
            const isHi      = highlight?.includes(k);
            return (
              <div key={k} className="contents">
                <dt className={isHi ? "font-semibold text-foreground/90" : "text-current/60 font-medium"}>{humanLabel(k)}</dt>
                <dd
                  className={
                    isHi
                      ? "text-foreground font-mono font-semibold truncate"
                      : "text-foreground/85 font-mono truncate"
                  }
                  title={typeof v === "string" ? v : formatted}
                >
                  {formatted}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      {nested.map(([k, v]) => (
        <NestedBlock key={k} label={humanLabel(k)} value={v} />
      ))}
    </div>
  );
}

/**
 * Smart renderer for the nested array/object values surfaced by the agent
 * decisions. We try to be useful for common shapes (operations list, machine
 * assignments, dimensions, etc.) before falling back to a raw JSON dump.
 */
function NestedBlock({ label, value }: { label: string; value: unknown }) {
  if (Array.isArray(value)) {
    const len = value.length;
    if (len === 0) {
      return (
        <div className="bg-muted/60 rounded p-2 text-[11px] text-current/50 italic">
          {label}: empty list
        </div>
      );
    }
    // Array of objects → render top N as inline rows. Array of primitives →
    // joined comma list.
    const isObjList = value.every((x) => x && typeof x === "object" && !Array.isArray(x));
    return (
      <details className="bg-muted/60 rounded p-2">
        <summary className="text-[10.5px] font-semibold text-current/60 uppercase tracking-wider cursor-pointer">
          {label} · {len} item{len === 1 ? "" : "s"}
        </summary>
        {isObjList ? (
          <ul className="mt-1.5 space-y-1.5">
            {value.slice(0, 6).map((row, i) => (
              <li key={i} className="border-t border-current/10 pt-1 first:border-0 first:pt-0">
                <ReadablePayload payload={row as Record<string, unknown>} />
              </li>
            ))}
            {len > 6 && (
              <li className="text-[10px] text-current/50 italic">… and {len - 6} more</li>
            )}
          </ul>
        ) : (
          <div className="mt-1.5 text-[11px] font-mono text-foreground/80 break-words">
            {value.map((v) => String(v)).join(", ")}
          </div>
        )}
      </details>
    );
  }

  // Object → recurse into ReadablePayload inside a details block.
  return (
    <details className="bg-muted/60 rounded p-2">
      <summary className="text-[10.5px] font-semibold text-current/60 uppercase tracking-wider cursor-pointer">
        {label}
      </summary>
      <div className="mt-1.5">
        <ReadablePayload payload={value as Record<string, unknown>} />
      </div>
    </details>
  );
}
