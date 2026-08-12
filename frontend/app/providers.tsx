"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";
import { makeQueryClient } from "@/lib/query/client";
import { NotifyPreferenceProvider } from "@/lib/notify/NotifyPreferenceProvider";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";

/**
 * Client-side providers. The only global client concerns are TanStack Query and the two persisted
 * client-only preferences (the theme, and the completion-signal mute toggle) — there is
 * deliberately **no** cross-page data store (MASTER_SPEC Part 7 §5.1: "server state is the
 * state"; the Redux rejection is honored by construction). Every wizard step reconstructs from a
 * `GET` keyed by the resource ID in its URL.
 */
export function Providers({ children }: { children: ReactNode }) {
  // One client per browser session, created lazily so it is not shared across SSR requests.
  const [queryClient] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <NotifyPreferenceProvider>{children}</NotifyPreferenceProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
