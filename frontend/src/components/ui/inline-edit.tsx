"use client";

/**
 * Double-click-to-edit cell.
 *
 * Shows a value (or a formatted `display` node); double-clicking anywhere in
 * the cell turns it into an input with explicit ✓ confirm / ✗ cancel controls.
 * Enter or ✓ commits (calls `onSave`); Escape or ✗ cancels; clicking away
 * (blur) commits the current draft. The non-editing state fills the whole cell
 * (`block w-full`) so even an empty "—" is an easy, full-width target — not a
 * 1-character hit box. Long text truncates to one line so rows stay aligned.
 *
 * Used by the Part Information and Bill-of-Material inline editors — the parent
 * owns the optimistic value + persistence; this just drives the edit affordance.
 */
import { useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export function InlineEdit({
  value,
  onSave,
  display,
  className,
  inputClassName,
  placeholder = "—",
  type = "text",
  align = "left",
  disabled = false,
}: {
  /** The raw, editable string (what the input binds to). */
  value: string;
  onSave: (next: string) => void;
  /** Optional formatted node shown when not editing (e.g. "$46.00", "31 min").
   *  The input still edits the raw `value`. */
  display?: React.ReactNode;
  className?: string;
  inputClassName?: string;
  placeholder?: string;
  type?: "text" | "number";
  align?: "left" | "right";
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(value);
      requestAnimationFrame(() => ref.current?.select());
    }
  }, [editing, value]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) onSave(draft);
  };
  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  if (editing) {
    return (
      <span className="flex w-full items-center gap-0.5">
        <input
          ref={ref}
          type={type}
          inputMode={type === "number" ? "decimal" : undefined}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter") { e.preventDefault(); commit(); }
            else if (e.key === "Escape") { e.preventDefault(); cancel(); }
          }}
          className={cn(
            "min-w-0 flex-1 rounded border border-primary/60 bg-background px-1.5 py-0.5 text-sm outline-none focus:ring-1 focus:ring-inset focus:ring-primary/30",
            align === "right" && "text-right tabular-nums",
            inputClassName,
          )}
        />
        {/* `onMouseDown preventDefault` keeps focus on the input so its blur
            doesn't fire a duplicate commit before this click's handler runs. */}
        <button
          type="button"
          title="Confirm (Enter)"
          aria-label="Confirm edit"
          onMouseDown={(e) => e.preventDefault()}
          onClick={(e) => { e.stopPropagation(); commit(); }}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-emerald-600 transition-colors hover:bg-emerald-100"
        >
          <Check className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          title="Cancel (Esc)"
          aria-label="Cancel edit"
          onMouseDown={(e) => e.preventDefault()}
          onClick={(e) => { e.stopPropagation(); cancel(); }}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </span>
    );
  }

  return (
    <span
      title={disabled ? undefined : "Double-click to edit"}
      onDoubleClick={disabled ? undefined : (e) => { e.stopPropagation(); setEditing(true); }}
      className={cn(
        // Full content, wrapped (never clipped) — the BoM must show every
        // column in full (1 June review item: "Content in all columns need to
        // be fully displayed"). `break-words` breaks over-long unbroken tokens
        // so a wide value can't blow the column width.
        "block w-full break-words rounded px-1 py-0.5",
        align === "right" && "text-right tabular-nums",
        !disabled && "cursor-text hover:bg-primary/5 hover:ring-1 hover:ring-inset hover:ring-primary/15",
        className,
      )}
    >
      {display != null
        ? display
        : value !== "" ? value : <span className="text-muted-foreground/50">{placeholder}</span>}
    </span>
  );
}
