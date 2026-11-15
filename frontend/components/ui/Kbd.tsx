import type { ReactNode } from "react";

/** A keyboard key as shown in the shortcut hints, the ⌘K trigger and the shortcut sheet (redesign §9). */
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  const base =
    "inline-flex min-w-4 items-center justify-center rounded-sm border border-line bg-well px-1 font-mono text-xs2 text-muted";
  return <kbd className={className ? `${base} ${className}` : base}>{children}</kbd>;
}
