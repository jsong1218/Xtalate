"use client";

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import { historyInfiniteQuery, limitsQuery, queryKeys } from "@/lib/api/queries";
import type { RetentionPolicy } from "./DeleteFileControl";
import { HistoryTableView } from "./HistoryTableView";

/**
 * The client wiring behind `/history` (Part 7 §5.1; slice M33-S2) — thin by design, exactly like the
 * other data pages. It fetches the keyset pages with `useInfiniteQuery` (the cursor contract lives in
 * {@link historyInfiniteQuery}), reads the instance's retention windows so the delete confirmation
 * can name them, and re-reads the list after a delete rather than editing the cache — so the row
 * reflects the server (its report intact, its `file_id` gone), never an optimistic guess. Every
 * load-bearing decision is in the tested pieces below it; here we only turn query state into one of
 * four honest surfaces: loading, error, empty, or the table.
 */
export function HistoryTable() {
  const queryClient = useQueryClient();
  const history = useInfiniteQuery(historyInfiniteQuery());
  const limits = useQuery(limitsQuery());

  const retention: RetentionPolicy | null = limits.data
    ? {
        uploadHours: limits.data.upload_retention_hours,
        reportHours: limits.data.report_retention_hours,
        reportDays: limits.data.report_retention_days,
      }
    : null;

  if (history.isPending) {
    return <p className="text-muted">Loading your conversion history…</p>;
  }

  if (history.isError) {
    return (
      <ErrorEnvelope
        envelope={toErrorEnvelope(
          history.error,
          "HISTORY_UNAVAILABLE",
          "The conversion history could not be loaded right now.",
        )}
      />
    );
  }

  const items = history.data.pages.flatMap((page) => page.items);

  if (items.length === 0) {
    return (
      <p className="text-body">
        No conversions yet. Once you convert a file, it will appear here with a full record of what
        was kept, dropped, or recovered.
      </p>
    );
  }

  return (
    <HistoryTableView
      items={items}
      hasMore={history.hasNextPage}
      onLoadMore={() => history.fetchNextPage()}
      loadingMore={history.isFetchingNextPage}
      retention={retention}
      onFileDeleted={() => queryClient.invalidateQueries({ queryKey: queryKeys.history })}
    />
  );
}
