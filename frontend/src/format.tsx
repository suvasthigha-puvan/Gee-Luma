import type { ReactNode } from "react";

/** Number with a sensible count of digits for its size. */
export function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const magnitude = Math.abs(value);
  if (magnitude === 0) return "0";
  if (magnitude >= 10000) return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (magnitude >= 100) return value.toFixed(1);
  if (magnitude >= 1) return value.toFixed(2);
  if (magnitude >= 0.001) return value.toFixed(4);
  return value.toExponential(2);
}

export function formatArea(km2: number | null | undefined): string {
  if (km2 === null || km2 === undefined) return "–";
  if (km2 >= 100) return `${Math.round(km2).toLocaleString("en-US")} km²`;
  if (km2 >= 1) return `${km2.toFixed(1)} km²`;
  return `${km2.toFixed(2)} km²`;
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export function timeAgo(unixSeconds: number): string {
  const minutes = Math.round((Date.now() / 1000 - unixSeconds) / 60);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return `${hours} h ago`;
}

/**
 * Server messages are written with light Markdown: **bold** and `code`.
 * Render just those two, as elements (never as HTML).
 */
export function richText(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return part;
  });
}
