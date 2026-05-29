/** Shared display formatters. */

/** USD with 2 decimals; ``—`` for null/undefined/NaN. */
export function usd(n: unknown): string {
  if (typeof n !== "number" || !isFinite(n)) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Minutes with a trailing unit; ``—`` for null/undefined/NaN. */
export function minutes(n: unknown, digits = 1): string {
  if (typeof n !== "number" || !isFinite(n)) return "—";
  return `${n.toFixed(digits)} min`;
}

/** Plain number, trimming trailing zeros; empty string when not a number. */
export function num(n: unknown, digits = 2): string {
  if (typeof n !== "number" || !isFinite(n)) return "";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

/** Coerce a form value to a finite number, else 0. */
export function toNum(v: string | number | null | undefined): number {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return isFinite(n) ? n : 0;
}

/** Short calendar date (e.g. "11 May 2026"); accepts seconds or ms epoch. */
export function dateShort(epoch: number): string {
  if (typeof epoch !== "number" || !isFinite(epoch) || epoch <= 0) return "—";
  const ms = epoch < 1e12 ? epoch * 1000 : epoch; // tolerate seconds
  return new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** Relative "time ago" for run timestamps (accepts seconds or ms epoch). */
export function timeAgo(epoch: number): string {
  const ms = epoch < 1e12 ? epoch * 1000 : epoch; // tolerate seconds
  const diff = Date.now() - ms;
  if (diff < 0) return "just now";
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(ms).toLocaleDateString();
}
