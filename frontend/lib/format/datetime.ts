/**
 * Deterministic UTC datetime formatting for report and record surfaces (Part 7 §2).
 *
 * A rendered date must not depend on the viewer's timezone — a conversion record and a recovery
 * deadline are shared, reproducible artifacts, so two people looking at the same one must read the
 * same wall-clock. We format in UTC with an explicit locale. Callers keep the exact ISO string in a
 * `<time dateTime>` attribute; this is only the human-readable face. A value that does not parse is
 * returned unchanged rather than rendered as "Invalid Date".
 */
export function formatUtc(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(date);
}
