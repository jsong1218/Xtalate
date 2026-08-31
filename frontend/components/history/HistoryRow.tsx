import Link from "next/link";
import { LossTag } from "@/components/loss/icons";
import { SummaryCountChips } from "@/components/report/SummaryChips";
import { formatUtc } from "@/lib/format/datetime";
import { historyStatus, type HistoryItem } from "@/lib/history/status";
import { DeleteFileControl, type RetentionPolicy } from "./DeleteFileControl";

/**
 * One `GET /v1/history` row (Part 7 §2.6; slice M33-S2). It renders exactly what the envelope
 * carries — never inferring a field the endpoint omitted.
 *
 * The load-bearing honesty is the **expired-bytes state**. `conversion_id` is durable until report
 * retention, so "open record" always resolves — the conversion report outlives the source bytes.
 * `file_id`, by contrast, is present *only while the upload is still live* (Part 6 §4.4), so it is
 * the single gate on the two actions that need those bytes: re-convert and delete. When it is gone,
 * the row does not show a dead button or a link that would 404 — it states the reason ("source file
 * expired") and keeps the report reachable. That is reports-outlive-bytes, visible in a row.
 *
 * When the upload *is* still live, "Open record" threads that `file_id` forward as `?file_id=`
 * (v0.7 review F7): the record page reads it (`useSearchParams`) because the record carries none of
 * its own, and it is what lets a refused record's "resolve and retry" re-submit the same upload
 * instead of degrading to a fresh-upload prompt for bytes that are demonstrably still here.
 */
function endpointLabel(endpoint: { format_id?: unknown; filename?: unknown }): {
  formatId: string;
  filename: string | null;
} {
  const formatId = typeof endpoint.format_id === "string" ? endpoint.format_id : "unknown";
  const filename = typeof endpoint.filename === "string" ? endpoint.filename : null;
  return { formatId, filename };
}

export function HistoryRow({
  item,
  retention,
  onFileDeleted,
}: {
  item: HistoryItem;
  retention: RetentionPolicy | null;
  onFileDeleted: () => void;
}) {
  const status = historyStatus(item);
  const source = endpointLabel(item.source);
  const target = endpointLabel(item.target);

  return (
    <tr data-testid={`history-row-${item.conversion_id}`} className="border-t border-line align-top">
      <td className="whitespace-nowrap px-3 py-3 text-sm text-muted">
        <time dateTime={item.created_at}>{formatUtc(item.created_at)}</time>
      </td>

      <td className="px-3 py-3 text-sm">
        <span className="font-medium text-strong">{source.formatId}</span>
        <span aria-hidden="true" className="mx-1 text-faint">
          →
        </span>
        <span className="font-medium text-strong">{target.formatId}</span>
        {source.filename ? (
          <span className="block break-all text-xs text-faint">{source.filename}</span>
        ) : null}
      </td>

      <td className="px-3 py-3">
        <LossTag kind={status.kind}>{status.label}</LossTag>
      </td>

      <td className="px-3 py-3">
        <SummaryCountChips counts={item.summary_counts} />
      </td>

      <td className="px-3 py-3">
        <div className="flex flex-col items-start gap-2">
          <Link
            href={
              item.file_id
                ? `/f/${item.file_id}/report/${item.conversion_id}`
                : `/conversions/${item.conversion_id}`
            }
            className="text-sm text-body underline underline-offset-2 hover:text-strong"
          >
            Open record
          </Link>
          {item.file_id ? (
            <>
              <Link
                href={`/f/${item.file_id}/convert`}
                className="text-sm text-body underline underline-offset-2 hover:text-strong"
              >
                Re-convert
              </Link>
              <DeleteFileControl
                fileId={item.file_id}
                retention={retention}
                onDeleted={onFileDeleted}
              />
            </>
          ) : (
            <span className="text-xs text-faint">
              Source file expired — the report stays readable, but re-converting needs a fresh upload.
            </span>
          )}
        </div>
      </td>
    </tr>
  );
}
