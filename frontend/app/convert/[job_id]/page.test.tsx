import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConversionJobPage from "./page";
import awaitingJob from "@/components/__fixtures__/job.awaiting_recovery.json";
import cancelledJob from "@/components/__fixtures__/job.cancelled.json";
import expiredJob from "@/components/__fixtures__/job.expired.json";
import failedJob from "@/components/__fixtures__/job.failed.json";

/**
 * The job page's terminal states (MASTER_SPEC Part 7 §2.4; slice M29-S1).
 *
 * Each fixture is a real `GET /v1/jobs/{id}` body captured from the service in-process, so these
 * assertions run against envelopes the backend actually emits — including the `expired` one, whose
 * error body carries `RECOVERY_REQUIRED` and the id of the refusal that was recorded.
 *
 * Two rules are the reason this test exists:
 *  1. An **expired** job says the conversion was *refused because no choice was made* — never that
 *     a default was applied.
 *  2. A **cancelled** job says no report exists, rather than rendering an empty report shell.
 */

vi.mock("next/navigation", () => ({
  useParams: () => ({ job_id: "job-under-test" }),
}));

/**
 * The transport is stubbed at the typed client, not at `fetch`: the app's client is deliberately
 * same-origin (an empty base URL), which a browser resolves and jsdom's URL parser does not. Mocking
 * here keeps the real `jobQuery` — its long-poll wiring and terminal-state stop condition — under test.
 */
const apiGet = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: (...args: unknown[]) => apiGet(...args),
    POST: vi.fn(async () => ({ data: undefined, error: undefined })),
  },
}));

function renderWithEnvelope(envelope: unknown) {
  apiGet.mockResolvedValue({ data: envelope, error: undefined });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConversionJobPage />
    </QueryClientProvider>,
  );
}

describe("ConversionJobPage terminal states", () => {
  it("renders an expired pause as a refusal for want of a decision, not a default", async () => {
    renderWithEnvelope(expiredJob);
    const card = await screen.findByRole("region", {
      name: /refused — no recovery choice was made/i,
    });
    expect(card).toHaveTextContent(/refused the conversion/i);
    expect(card).toHaveTextContent(/no default was applied/i);
    expect(card).toHaveTextContent(/no value was invented/i);
    // The service's own code, verbatim, alongside the plain-language card.
    expect(await screen.findByText("RECOVERY_REQUIRED")).toBeInTheDocument();
  });

  it("renders a cancelled job as having no report, not an empty one", async () => {
    renderWithEnvelope(cancelledJob);
    const card = await screen.findByRole("region", { name: /cancelled/i });
    expect(card).toHaveTextContent(/no report exists for it/i);
    // No report panel was rendered in its place.
    expect(screen.queryByText(/preserved/i)).not.toBeInTheDocument();
  });

  it("renders a failed job through the shared error envelope, code verbatim", async () => {
    renderWithEnvelope(failedJob);
    expect(await screen.findByText("UNKNOWN_FORMAT")).toBeInTheDocument();
  });

  it("renders a paused job's placeholder with both unresolved scenarios", async () => {
    renderWithEnvelope(awaitingJob);
    expect(await screen.findByTestId("awaiting-recovery")).toBeInTheDocument();
    expect(screen.getAllByTestId("awaiting-scenario")).toHaveLength(2);
  });

  it("offers Cancel while paused (a non-terminal state) and calls it best-effort", async () => {
    renderWithEnvelope(awaitingJob);
    const cancel = await screen.findByRole("button", { name: /cancel this conversion/i });
    expect(cancel).toBeInTheDocument();
    expect(screen.getByText(/best-effort/i)).toBeInTheDocument();
  });

  it("offers no Cancel once the job is terminal", async () => {
    renderWithEnvelope(cancelledJob);
    await screen.findByRole("region", { name: /cancelled/i });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /cancel this conversion/i })).toBeNull(),
    );
  });
});
