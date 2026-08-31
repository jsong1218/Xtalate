/**
 * **Recent files** — the strip (and the palette's "recent" section) that gets you back to a file
 * you were just working on (UI redesign S4, D246; D-R6 — client-side only).
 *
 * Two sources, one list:
 *  - a **localStorage** recents list (`xtalate-recents`), written each time a workspace is visited
 *    (the Inspect tab pushes the file), so a file you opened seconds ago is one click away and
 *    survives a reload; and
 *  - **`/v1/history`**, seeded by the caller (the landing's strip) and merged in — the durable list
 *    of a session's conversions, so a just-converted output is reachable even before this browser
 *    touched the workspace (a shared link, a second tab).
 *
 * Every entry is keyed by `file_id` when the source upload is still live (a workspace URL), else by
 * `conversion_id` (a durable record URL) — mirroring the HistoryRow rule. The list is capped and
 * de-duplicated by that key, enthusiastically overwriting a re-seen entry so its position jumps to
 * the front (recency, not birth order).
 */
import { readJson, writeJson } from "./storage";

/** One recent-file entry, normalized for the strip and the palette. */
export interface RecentFile {
  /** The stable identity — `file_id` when live, else `conversion_id`. */
  key: string;
  /** A workspace URL when the source upload is live, else the durable record URL. */
  href: string;
  filename: string;
  /** The source format id (for the strip's "extXYZ" tag and the palette search). */
  format_id: string;
  /** ISO timestamp of when it was *last seen* (a sort key). */
  last_seen_at: string;
}

export const RECENTS_STORAGE_KEY = "recents";

/** Strip + palette cap — recency needs a handful, not a wall (Part 7 §4.2 lightweight). */
export const MAX_RECENTS = 8;

function isRecent(v: unknown): v is RecentFile {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.key === "string" &&
    typeof r.href === "string" &&
    typeof r.filename === "string" &&
    typeof r.format_id === "string" &&
    typeof r.last_seen_at === "string"
  );
}

function isRecentList(v: unknown): v is RecentFile[] {
  return Array.isArray(v) && v.every(isRecent);
}

/** Read the persisted recents (never throws). */
export function listRecents(): RecentFile[] {
  return readJson<RecentFile[]>(RECENTS_STORAGE_KEY, isRecentList, []);
}

/** Merge two recency lists, de-duplicated by `key`, most-recent-first, capped. */
function mergeRecency<It extends { key: string }>(a: It[], b: It[], cap: number): It[] {
  const seen = new Set<string>();
  const out: It[] = [];
  for (const it of [...a, ...b]) {
    if (seen.has(it.key)) continue;
    seen.add(it.key);
    out.push(it);
    if (out.length >= cap) break;
  }
  return out;
}

/**
 * Record that `entry` was just visited: it jumps to the front, pre-existing duplicates vanish, and
 * the list stays capped. `href`/`filename` are refreshed from the current visit (a file's record
 * URL may have outlived its upload). Returns whether the write landed.
 */
export function pushRecent(entry: Omit<RecentFile, "key"> & { key: string }): boolean {
  const now = new Date().toISOString();
  const current = listRecents().filter((r) => r.key !== entry.key);
  const next = mergeRecency([{ ...entry, last_seen_at: now }, ...current], [], MAX_RECENTS);
  return writeJson(RECENTS_STORAGE_KEY, next);
}

/**
 * Merge the persisted recents with a seeded list (from `/v1/history`) — most recent first, the
 * persisted wins ties by key. The strip calls this with the history-derived entries so a just-made
 * conversion appears without this browser having visited its workspace.
 */
export function mergeRecents(persisted: RecentFile[], seeded: RecentFile[]): RecentFile[] {
  return mergeRecency(persisted, seeded, MAX_RECENTS);
}