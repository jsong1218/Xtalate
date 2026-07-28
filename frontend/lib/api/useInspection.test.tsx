import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useInspection } from "./useInspection";
import cancelledJob from "@/components/__fixtures__/job.cancelled.json";

/**
 * The transport is stubbed at the typed client, not at `fetch`: the app's client is deliberately
 * same-origin (an empty base URL) and openapi-fetch binds `globalThis.fetch` at client-creation
 * time, so a late `vi.stubGlobal("fetch", …)` never reaches it. Mocking here — the repo's
 * convention (see `app/convert/[job_id]/page.test.tsx`) — keeps the real `useInspection` projection
 * and the real `isTerminalJobState` stop condition under test.
 */
const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: (...args: unknown[]) => apiGet(...args),
    POST: (...args: unknown[]) => apiPost(...args),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

it("renders a cancelled inspect job as an honest error, never an eternal spinner", async () => {
  apiPost.mockResolvedValue({ data: { job_id: "job_1", state: "queued" }, error: undefined });
  apiGet.mockResolvedValue({ data: cancelledJob, error: undefined });

  const { result } = renderHook(() => useInspection("file_1"), { wrapper });

  await waitFor(() => expect(result.current.status).toBe("error"));
  expect(result.current.status === "error" && result.current.error.error.code).toBe(
    "INSPECTION_CANCELLED",
  );
});
