import { HistoryRow } from "./HistoryRow";
import type { RetentionPolicy } from "./DeleteFileControl";
import type { HistoryItem } from "@/lib/history/status";

/**
 * The presentational history table (Part 7 §2.6; slice M33-S2) — the load-bearing decisions live in
 * the pure pieces it composes (`historyStatus`, `SummaryCountChips`, `HistoryRow`), so this only
 * lays out the columns and the cursor "Load more" control. It never computes an offset: pagination
 * is driven entirely by `hasMore`/`onLoadMore`, which the wiring component derives from the server's
 * opaque `next_cursor`. The table scrolls horizontally rather than forcing the page to, so the
 * per-row loss chips stay legible on a narrow screen.
 */
export function HistoryTableView({
  items,
  hasMore,
  onLoadMore,
  loadingMore = false,
  retention,
  onFileDeleted,
}: {
  items: HistoryItem[];
  hasMore: boolean;
  onLoadMore: () => void;
  loadingMore?: boolean;
  retention: RetentionPolicy | null;
  onFileDeleted: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-raised text-xs uppercase tracking-wide text-faint">
              <th scope="col" className="px-3 py-2 font-medium">
                When
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Conversion
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Status
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                Summary
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <HistoryRow
                key={item.conversion_id}
                item={item}
                retention={retention}
                onFileDeleted={onFileDeleted}
              />
            ))}
          </tbody>
        </table>
      </div>

      {hasMore ? (
        <div>
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loadingMore}
            className="rounded-md border border-line px-4 py-2 text-sm font-medium text-body disabled:opacity-60"
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
