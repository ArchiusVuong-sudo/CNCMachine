/**
 * Wire-format types for the Python FastAPI backend.
 *
 * These mirror the shapes the new server emits, NOT the Supabase row
 * shapes. The server side is in ``E:\\data\\server`` — relevant files:
 *
 *   - ``server/pipeline/orchestrator.py:389``  — final results envelope
 *   - ``server/core/schemas/drawing.py``       — VLM extraction
 *   - ``server/engines/process_mapping/cost_engine.py`` — catalog columns
 *   - ``server/api/routes/analyses.py``        — AnalysisSummary
 *   - ``server/api/routes/catalog.py``         — catalog CRUD bodies
 *
 * Everything is loose at the edges (``Record<string, unknown>`` /
 * optional fields) because the backend uses Pydantic ``extra="allow"``
 * and tolerates Supabase schema drift; the FE should not crash if a
 * column appears or disappears.
 */

// ---------------------------------------------------------------------------
// SSE stream message (assembled by useAnalysisStream from analyze-stream frames)
// ---------------------------------------------------------------------------

export interface AgentStreamMessage {
  id:        string;
  type:      string;
  data:      Record<string, unknown>;
  timestamp: number;
}

// ---------------------------------------------------------------------------
// VLM (drawing) extraction
// ---------------------------------------------------------------------------

export interface BomItem {
  item_no:      number;
  part_number:  string;
  description?: string;
  qty?:         number;
  tengc?:       string;
  material?:    string;
  part_type?:   string;
  unit_price?:  number | null;
  [key: string]: unknown;
}

/** Mirrors server ``DimensionRow`` (core/schemas/drawing.py). */
export interface DimensionRow {
  label?:           string;
  nominal?:         number | string;
  unit?:            string;
  tolerance_plus?:  number | null;
  tolerance_minus?: number | null;
  tolerance?:       string;
  notes?:           string;
  [key: string]: unknown;
}

/** Mirrors server ``GdtCallout``. */
export interface GdtCallout {
  symbol?:        string;
  tolerance?:     string;
  datum_refs?:    string[];
  feature_label?: string;
  [key: string]: unknown;
}

/** Mirrors server ``ThreadSpec``. */
export interface ThreadSpec {
  spec?:     string;
  label?:    string;
  count?:    number;
  depth_mm?: number;
  is_blind?: boolean;
  [key: string]: unknown;
}

/** Mirrors server ``TitleBlock``. */
export interface TitleBlock {
  part_number?:    string;
  revision?:       string;
  title?:          string;
  description?:    string;
  drawn_by?:       string;
  checked_by?:     string;
  date?:           string;
  company?:        string;
  scale?:          string;
  sheet?:          string;
  dimension_unit?: string;
  [key: string]: unknown;
}

export interface VlmExtraction {
  part_number?:     string;
  revision?:        string;
  description?:     string;
  material?:        string;
  surface_finish?:  string | null;
  dimension_unit?:  "mm" | "in" | string;
  /** Drawing-level family (brief Page 3 OCR output): weldment |
   *  assembly_bolted | assembly_bonded | sheet_metal | cnc_milling | … */
  part_category?:   string | null;
  /** Drawing mfg spec: welded | bolted | riveted | bonded | null. */
  assembly_method?: string | null;
  title_block?:     TitleBlock | null;
  bom_items?:       BomItem[];
  /** Server emits ``list[str]``; tolerate ``{text}`` objects defensively. */
  drawing_notes?:   (string | { text?: string })[];
  dimensions?:      DimensionRow[];
  gdt_callouts?:    GdtCallout[];
  threads?:         ThreadSpec[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// 3D assembly
// ---------------------------------------------------------------------------

export interface BBox {
  length_mm: number;
  width_mm:  number;
  height_mm: number;
}

export interface Thickness {
  min_mm:     number;
  max_mm:     number;
  mean_mm:    number;
  std_dev_mm: number;
  is_uniform: boolean;
}

export interface WeldingContact {
  comp_a:            string;
  comp_b:            string;
  contact_length_mm: number;
  contact_type:      "edge" | "face" | string;
}

export interface AssemblyData {
  component_count:  number;
  total_volume_mm3: number;
  pmi_available:    boolean;
  welding_contacts: WeldingContact[];
}

// ---------------------------------------------------------------------------
// Per-component
// ---------------------------------------------------------------------------

export interface FeatureDimensions {
  diameter_mm?:     number;
  depth_mm?:        number;
  width_mm?:        number;
  length_mm?:       number;
  radius_mm?:       number;
  angle_deg?:       number;
  thread_pitch_mm?: number;
  [key: string]: number | undefined;
}

export interface FeatureLocation { x: number; y: number; z: number; }

export interface Feature {
  feature_index:    number;
  feature_type:     string;
  face_ids?:        number[];
  count?:           number;
  confidence?:      number;
  source?:          string;
  dimensions?:      FeatureDimensions;
  perimeter_mm?:    number;
  location?:        FeatureLocation;
  tolerance_plus?:  number | null;
  tolerance_minus?: number | null;
  gdt_callouts?:    string[];
  /** dim_tagger flags carried on the feature. */
  tolerance_class?: string;
  is_threaded?:     boolean;
  thread_spec?:     string;
  operations?:      string[];
  needs_finishing?: boolean;
  key_face_id?:     string;
  [key: string]: unknown;
}

/** One row of the per-feature ↔ tolerance/GD&T/process map (UI projection). */
export interface FeatureMapRow {
  feature_id:       string;
  feature_type:     string;
  count?:           number;
  key_dimension?:   string;
  tolerance?:       string;
  tolerance_class?: string;
  gdt?:             string;
  thread?:          string;
  operations?:      string;
}

/** One ranked machine returned by Phase A. */
export interface RankedMachine {
  rank?:           number;
  machine_id?:     string | null;
  machine_name?:   string;
  machine_type?:   string;
  hourly_rate_usd?: number;
  score?:          number;
  [key: string]: unknown;
}

/** Output of one Phase B routing operation. */
export interface AgenticOperation {
  op_code?:           string;
  op_index?:          number;
  name?:              string;
  description?:       string;
  setup_min_per_lot?: number;
  feature_ids?:       number[];
  [key: string]: unknown;
}

/** Output of one Phase C tool pick (mirrors operations order). */
export interface AgenticTool {
  op_index?:    number;
  op_code?:     string;
  tool_id?:     string | null;
  tool_name?:   string;
  tool_type?:   string;
  diameter_mm?: number;
  flute_no?:    number;
  length_mm?:   number;
  dimensions?:  Record<string, number>;
  [key: string]: unknown;
}

/** Output of one Phase D parameters row. */
export interface AgenticParameters {
  op_index?:           number;
  op_code?:            string;
  spindle_rpm?:        number;
  feed_mm_per_min?:    number;
  depth_of_cut_mm?:    number;
  cut_length_mm?:      number;
  cycle_time_min?:     number;
  [key: string]: unknown;
}

/** Engine-agnostic per-component planner payload — whichever planner engine
 *  ran (in-house agentic, external CAM planner, manual override, etc.) attaches
 *  its output here. The legacy `agentic` key on Component is still read as a
 *  fallback for runs persisted before the rename. */
export interface PlannerData {
  machine_class?:            string;
  chosen_machine_id?:        string | null;
  ranked_machines?:          RankedMachine[];
  /** Alias seen in some payloads. */
  top_machines?:             RankedMachine[];
  operations?:               AgenticOperation[];
  tools_per_operation?:      AgenticTool[];
  parameters_per_operation?: AgenticParameters[];
  total_run_min_per_part?:   number;
  setup_min_per_lot?:        number;
  analogues_used?:           string[];
  fallback_rungs?:           Record<string, unknown>;
  iterations_by_phase?:      Record<string, number>;
  tool_call_count_by_phase?: Record<string, number>;
  /** True when this component is a consolidated child of another and its
   *  machining was rolled into the assembly owner. Used to avoid double-
   *  counting cycle time / cost. */
  suppressed_by_consolidation_gate?: boolean;
  error?:                    string | null;
  [key: string]: unknown;
}

/** One row in ``processes_per_component[i]`` — flat routing/cost row.
 *  Field names mirror server `core/schemas/plan.RoutingRow` (Pydantic) 1:1
 *  so a different planner engine emitting the same Pydantic shape Just Works
 *  without an FE adapter. */
export interface RoutingRow {
  /** Position in the routing sequence (1, 2, 3…). Mirrors Pydantic
   *  `RoutingRow.sequence`. */
  sequence?:         number;
  op_code?:          string;
  op_id?:            string;
  process_type?:     string;
  category?:         string;
  /** String feature IDs (Pydantic `feature_ids: list[str]`). */
  feature_ids?:      string[];
  operation_count?:  number;
  /** Flat machine fields (mirror Pydantic). */
  machine_id?:       string | null;
  machine_name?:     string;
  /** Flat tooling fields (mirror Pydantic). */
  tool_ids?:         string[];
  tool_type?:        string;
  tool_dimensions?:  Record<string, number>;
  spindle_rpm?:      number;
  feed_mm_per_min?:  number;
  depth_of_cut_mm?:  number;
  cut_length_mm?:    number;
  cycle_time_min?:   number;
  setup_min_per_lot?: number;
  run_min_per_part?: number;
  labor_cost_usd?:   number;
  machine_cost_usd?: number;
  tool_cost_usd?:    number;
  total_cost_usd?:   number;
  /** Machining complexity rating (backend-supplied; e.g. "Low"/"Medium"/"High"). */
  complexity?:       string | number;
  notes?:            string;
  [key: string]: unknown;
}

export interface StockInfo {
  stock_id?:           string | null;
  material_name?:      string;
  material_form?:      string;
  cost_per_stock_usd?: number;
  qty_per_stock?:      number;
  waste_ratio?:        number;
  stock_dimensions?:   BBox;
  [key: string]: unknown;
}

export interface ComponentCost {
  raw_material_usd?:          number;
  setup_usd?:                 number;
  machining_usd_by_process?:  Record<string, number>;
  deburr_usd?:                number;
  inspection_usd?:            number;
  total_usd?:                 number;
  [key: string]: unknown;
}

export interface Component {
  id?:                    string;
  component_index:        number;
  name?:                  string;
  description?:           string;
  instance_count?:        number;
  part_type?:             string;
  part_type_confidence?:  number;
  volume_mm3?:            number;
  surface_area_mm2?:      number;
  bbox?:                  BBox;
  thickness?:             Thickness;
  total_perimeter_mm?:    number;
  mapped_to_bom_item?:    number | null;
  material?:              string;
  mapping_method?:        "description" | "tengc" | "unknown" | string;
  features?:              Feature[];
  /** Routing + per-op costing rows for this component. */
  manufacturing_processes?: RoutingRow[];
  /** Pre-adapter manufacturing_processes (per-tool feeds/speeds + tool detail),
   *  preserved by adoptCostedComponents() before the costed routing rows
   *  overwrite `manufacturing_processes`. The Manufacturing Plan card reads
   *  feeds/speeds from here. */
  raw_manufacturing_processes?: RoutingRow[];
  /** Alias kept for components that still use the legacy field name. */
  processes?:             RoutingRow[];
  stock?:                 StockInfo | null;
  cost?:                  ComponentCost;
  cycle_time_min?:        number;
  /** Overall machining complexity rating (backend-supplied). */
  complexity?:            string | number;
  /** Planner engine output (whichever engine ran — agentic, external, etc.). */
  planner?:               PlannerData;
  /** Legacy alias for runs persisted before the planner-rename. Consumers
   *  should prefer `planner` and treat this as a backwards-compat fallback. */
  agentic?:               PlannerData;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Cost / cycle-time aggregates
// ---------------------------------------------------------------------------

export interface CostBreakdownRow {
  component_index: number;
  total_usd:       number;
  /** Some payloads include the per-component cost sub-object inline. */
  cost?:           ComponentCost;
}

export interface CostBlock {
  total_usd?:               number;
  breakdown_by_component?:  CostBreakdownRow[];
}

export interface CycleTimeRow {
  component_index: number;
  total_minutes:   number;
}

export interface CycleTimeBlock {
  total_minutes?:           number;
  breakdown_by_component?:  CycleTimeRow[];
}

// ---------------------------------------------------------------------------
// CAM block (FreeCAD G-code)
// ---------------------------------------------------------------------------

export interface CamPerComponent {
  component_index: number;
  ok:              boolean;
  files?:          string[];
  error?:          string | null;
  [key: string]: unknown;
}

export interface CamBlock {
  ok:           boolean;
  error?:       string | null;
  by_component: CamPerComponent[];
  total_files?: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Category decisions (reconciler trace)
// ---------------------------------------------------------------------------

export interface CategoryDecision {
  component_index: number;
  final_category:  string;
  vlm_vote?:       string | null;
  vlm_confidence?: number | null;
  occ_vote?:       string | null;
  occ_confidence?: number | null;
  source:          "occ" | "vlm" | "user_override" | "fallback_occ" | string;
  user_forced?:    boolean;
}

// ---------------------------------------------------------------------------
// Top-level final-answer envelope from POST /v1/analyze-stream
// ---------------------------------------------------------------------------

export interface FinalAnswer {
  analysis_id:              string;
  approach:                 "modular_monolith";
  batch_size:               number;
  assembly_name?:           string;
  file_name?:               string;
  total_minutes:            number;
  total_usd:                number;
  elapsed_seconds:          number;
  vlm_extraction?:          VlmExtraction;
  assembly_data?:           AssemblyData;
  components:               Component[];
  processes_per_component?: RoutingRow[][];
  category_decisions?:      CategoryDecision[];
  cost?:                    CostBlock;
  cycle_time?:              CycleTimeBlock;
  cam?:                     CamBlock;
  /** Assembly-level cost rollup (per-piece / per-lot + confidence band). */
  cost_summary?: {
    total_usd_per_piece?: number;
    total_usd_per_lot?:   number;
    batch_size?:          number;
    confidence_band_pct?: number | null;
    evidence?:            unknown;
  } | null;
  /**
   * SSE pipeline events captured at the route layer and persisted into
   * the saved analysis JSON. Powers the History view's pipeline-activity
   * card so reopening a run shows the same timeline as the live stream.
   * Absent on runs persisted before the capture layer was added.
   */
  messages?:                AgentStreamMessage[];
  /**
   * Durable storage refs for the uploaded STEP / drawing, written by the
   * orchestrator. Lets the viewer re-sign URLs for a reopened run even
   * when this browser's localStorage source cache is empty (different
   * machine / cleared cache). All fields may be null when the run was
   * submitted as raw bytes rather than Supabase URLs.
   */
  sources?: {
    bucket?:       string | null;
    step_path?:    string | null;
    drawing_path?: string | null;
    file_name?:    string | null;
  };
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// History endpoints (GET /v1/analyses)
// ---------------------------------------------------------------------------

export interface AnalysisSummary {
  id:             string;
  file_name?:     string | null;
  assembly_name?: string | null;
  /** Drawing identity (server reads these from vlm_extraction). */
  part_number?:   string | null;
  revision?:      string | null;
  material?:      string | null;
  total_usd?:     number | null;
  total_minutes?: number | null;
  n_components?:  number | null;
  created_at:    number;
}

export interface AnalysisListResponse {
  data:  AnalysisSummary[];
  total: number;
}

// ---------------------------------------------------------------------------
// Catalog rows — Supabase columns; loose because Pydantic uses extra="allow"
// ---------------------------------------------------------------------------

export interface MachineRow {
  id:                string;
  user_id?:          string | null;
  machine_name:      string;
  machine_type?:     string;
  brand?:            string | null;
  model?:            string | null;
  hourly_rate_usd?:  number;
  axes?:             number | null;
  spindle_rpm_max?:  number | null;
  travel_x_mm?:      number | null;
  travel_y_mm?:      number | null;
  travel_z_mm?:      number | null;
  is_active:         boolean;
  notes?:            string | null;
  created_at?:       string;
  updated_at?:       string;
  [key: string]: unknown;
}

export interface ToolingRow {
  id:                  string;
  user_id?:            string | null;
  tool_name:           string;
  tool_type?:          string;
  diameter_mm?:        number | null;
  flute_count?:        number | null;
  flute_length_mm?:    number | null;
  overall_length_mm?:  number | null;
  shank_diameter_mm?:  number | null;
  material?:           string | null;
  coating?:            string | null;
  cost_usd?:           number | null;
  tool_life_minutes?:  number | null;
  is_active:           boolean;
  notes?:              string | null;
  tool_spec?:          string | null;
  [key: string]: unknown;
}

export interface LaborRateRow {
  id:               string;
  user_id?:         string | null;
  role_name:        string;
  hourly_rate_usd:  number;
  description?:     string | null;
  is_active:        boolean;
  [key: string]: unknown;
}

export interface MaterialStockRow {
  id:                  string;
  user_id?:            string | null;
  material_name:       string;
  material_form?:      string;
  stock_dimensions?:   Partial<BBox> & Record<string, unknown>;
  cost_per_stock_usd?: number | null;
  qty_per_stock?:      number | null;
  waste_ratio?:        number | null;
  supplier?:           string | null;
  is_active:           boolean;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Catalog create-bodies — only the columns we require; the rest pass through.
// ---------------------------------------------------------------------------

export interface MachineCreate {
  machine_name:    string;
  machine_type?:   string;
  hourly_rate_usd?: number;
  is_active?:      boolean;
  [key: string]: unknown;
}

export interface ToolingCreate {
  tool_name:  string;
  tool_type?: string;
  is_active?: boolean;
  [key: string]: unknown;
}

export interface LaborRateCreate {
  role_name:       string;
  hourly_rate_usd: number;
  is_active?:      boolean;
  [key: string]: unknown;
}

export interface MaterialStockCreate {
  material_name:  string;
  material_form?: string;
  is_active?:     boolean;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------

export interface HealthResponse {
  ok:          boolean;
  version?:    string;
  supabase?:   { configured: boolean };
  llm?:        { configured: boolean; url?: string };
  freecad?:    { configured: boolean };
  [key: string]: unknown;
}

export interface FeedbackPayload {
  analysis_id:  string;
  verdict?:     "good" | "bad" | "neutral" | string;
  comments?:    string;
  overrides?:   Record<string, unknown>;
  [key: string]: unknown;
}
