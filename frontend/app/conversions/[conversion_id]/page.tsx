"use client";

import { useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ConversionRecord } from "@/components/workspace/ConversionRecord";
import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/client";

/**
 * Ceiling on the legacy-bookmark history walk (VIEW-M2): 50 pages of 100 = 5,000 records, beyond
 * which the standalone fallback is the honest answer for a bookmark that deep in the past.
 */
const MAX_HISTORY_PAGES = 50;

/**
 * Legacy route (UI redesign S2, D244): the durable record now lives at
 * `/f/[file_id]/report/[cid]` (the workspace's Report tab). The record itself carries no `file_id`
 * (Part 6 §4.4), so resolution is two-stage:
 *
 *  - `?file_id=` handed forward (the app always does) → immediate redirect into the workspace.
 *  - a bare bookmarked URL → look the conversion up in `/v1/history`, whose rows carry `file_id`
 *    while the source upload is still live (Part 6 §4.4); if found, redirect into the workspace.
 *  - otherwise (the source bytes are long gone — reports outlive bytes) the record renders
 *    standalone, exactly as it always did: no 404, behaviour preserved.
 */
export default function LegacyConversionRecordPage() {
  const params = useParams<{ conversion_id: string }>();
  const conversionId = params.conversion_id;
  const fileId = useSearchParams().get("file_id");
  const router = useRouter();

  // Only fetch history when the caller didn't already hand a file forward.
  const history = useQuery({
    queryKey: queryKeys.history,
    queryFn: async () => {
      // A bookmark can point at a conversion older than the most-recent page. /v1/history is
      // keyset-paginated, so follow next_cursor until the record is found or the history is
      // exhausted, rather than searching only the first 100 and silently failing to redirect
      // (VIEW-M2). Bounded by a page cap so a very long history cannot loop unboundedly on the
      // client — beyond it, the standalone fallback below is the honest answer.
      let cursor: string | null = null;
      let match: Schemas["HistoryItem"] | undefined;
      for (let page = 0; page < MAX_HISTORY_PAGES && !match; page++) {
        // The explicit type breaks the inference cycle between the GET's generic response type
        // and the query object that parameterizes it (TS7022 otherwise).
        const query: { limit: number; cursor?: string } = cursor
          ? { limit: 100, cursor }
          : { limit: 100 };
        const { data, error } = await apiClient.GET("/v1/history", {
          params: { query },
        });
        if (error) throw error;
        match = data.items.find(
          (item) => item.conversion_id === conversionId && Boolean(item.file_id),
        );
        // `next_cursor` is optional on the schema; absent means the history is exhausted.
        cursor = data.next_cursor ?? null;
        if (cursor === null) break;
      }
      return { items: match ? [match] : [], next_cursor: null };
    },
    enabled: !fileId,
    // A bounded default retry: a transient fetch failure (a cold dev proxy, a hiccup) must not
    // permanently strand a resolvable bookmark on the standalone path — the lookup is one-shot
    // by design (no polling), so a failed attempt gets its bounded retries before giving up.
  });
  const resolvedFileId =
    fileId ??
    (history.data?.items ?? []).find(
      (item: Schemas["HistoryItem"]) =>
        item.conversion_id === conversionId && Boolean(item.file_id),
    )?.file_id ??
    null;

  useEffect(() => {
    if (resolvedFileId) {
      router.replace(`/f/${resolvedFileId}/report/${conversionId}`);
    }
  }, [resolvedFileId, conversionId, router]);

  return (
    <ConversionRecord
      conversionId={conversionId}
      fileId={resolvedFileId}
      inWorkspace={false}
    />
  );
}
