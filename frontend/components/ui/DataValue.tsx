import type { ReactNode } from "react";

/**
 * The mono wrapper for a rendered scientific value, count, or identifier (UI redesign S1, D243).
 * Values are shown monospace across the app — positions shapes, frame counts, hashes, file ids — so
 * a number is always visually a number. Defining it once keeps that consistent; `className` is for
 * layout only (margins, alignment), never to override the mono/colour base.
 */
export function DataValue({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const base = "font-mono text-strong";
  return <span className={className ? `${base} ${className}` : base}>{children}</span>;
}
