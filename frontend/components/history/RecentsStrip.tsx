"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useInfiniteQuery } from "@tanstack/react-query";
import { historyInfiniteQuery } from "@/lib/api/queries";
import type { HistoryItem } from "@/lib/history/status";
import { listRecents, MAX_RECENTS, mergeRecents, type RecentFile } from "@/lib/prefs/recents";

/**
 * The recent-files strip (UI redesign S4, D246; design spec §6.4) — one click back to a file you
 * were just working on. It merges two client-side sources per `lib/prefs/recents.ts`: the
 * **localStorage** recents (written when a workspace is visited) and **`/v1/history`** (the durable
 * list, so a just-made conversion appears even before this browser touched its workspace). Each chip
 * links into the file's workspace (`/f/[file_id]`) while its source upload is live, else to the
 * durable record — the reports-outlive-bytes rule, in a strip.
 *
 * It reads only endpoints and keys the app already uses — no new backend route (D-R6).
 */
function historyToRecent(item: HistoryItem): RecentFile | null {
  const source = item.source as { format_id?: unknown; filename?: unknown };
  const formatId = typeof source.format_id === "string" ? source.format_id : "";
  const filename = typeof source.filename === "string" ? source.filename : item.conversion_id;
  const fileId = typeof item.file_id === "string" ? item.file_id : null;
  // A live source gets a workspace link; a record whose bytes are gone resolves to the durable
  // record (the legacy redirect-or-standalone renders the full record either way).
  const href = fileId ? `/f/${fileId}` : `/conversions/${item.conversion_id}`;
  const key = fileId ?? item.conversion_id;
  return { key, href, filename, format_id: formatId, last_seen_at: item.created_at };
}

export function RecentsStrip() {
  const { data } = useInfiniteQuery(historyInfiniteQuery(MAX_RECENTS));
  const seeded = useMemo(
    () => (data?.pages[0]?.items ?? []).map(historyToRecent).filter((r): r is RecentFile => r !== null),
    [data],
  );
  // The persisted recents are read once — the strip is a snapshot of "recent", not a live counter.
  const persisted = useMemo(() => listRecents(), []);
  const recents = useMemo(() => mergeRecents(persisted, seeded), [persisted, seeded]);

  if (recents.length === 0) return null;

  return (
    <section aria-label="Recent files" className="space-y-2">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-strong">Recent files</h2>
        <span className="rounded bg-well px-1.5 py-0.5 text-xs text-faint">from this browser + history</span>
      </div>
      <ul className="flex flex-wrap gap-2" data-testid="recents-strip">
        {recents.map((r) => (
          <li key={r.key}>
            <Link
              href={r.href}
              className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-sm text-body transition-colors hover:bg-raised"
            >
              <span className="max-w-[12rem] truncate">{r.filename}</span>
              {r.format_id ? (
                <span className="rounded bg-well px-1 py-0.5 font-mono text-xs text-muted">
                  {r.format_id}
                </span>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}