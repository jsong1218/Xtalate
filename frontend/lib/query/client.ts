import { QueryClient } from "@tanstack/react-query";

/**
 * The shared TanStack Query client (MASTER_SPEC Part 7 §5.1).
 *
 * Defaults encode two spec rules:
 *  - **Reports are immutable.** `DiscoveryReport` / `ConversionReport` / `ValidationReport` never
 *    mutate — re-validation *appends* a new report (Part 6 §2) — so report queries are cached with
 *    an effectively infinite `staleTime` and refetched only on explicit invalidation. Per-query
 *    overrides (below, for job polling) opt back into refetching.
 *  - **Refetch-on-focus** is on so returning to a tab re-reads server state, the single source of
 *    truth (§5.1). Job-polling queries additionally use the `?wait=5` long-poll (Part 6 §3.1),
 *    configured where those queries are defined (M28/M29), not globally.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        refetchOnWindowFocus: true,
        retry: 1,
      },
    },
  });
}
