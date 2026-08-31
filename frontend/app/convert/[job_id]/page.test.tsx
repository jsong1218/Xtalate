import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConversionJobPage from "./page";
import { NotifyPreferenceProvider } from "@/lib/notify/NotifyPreferenceProvider";
import awaitingJob from "@/components/__fixtures__/job.awaiting_recovery.json";
import cancelledJob from "@/components/__fixtures__/job.cancelled.json";
import completedJob from "@/components/__fixtures__/job.completed.json";
import expiredJob from "@/components/__fixtures__/job.expired.json";
import failedJob from "@/components/__fixtures__/job.failed.json";
import batchAwaitingJob from "@/components/__fixtures__/job.batch_awaiting_recovery.json";
import batchCompletedJob from "@/components/__fixtures__/job.batch_completed.json";

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
  // A shared job link carries no `file_id`; the page must cope with that, so the default is empty.
  // (With a `file_id` the page redirects into the workspace — covered by the e2e redirect journey.)
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
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
  // The page mounts the completion-signal hook (v1.1 M39-S4 C1), which reads the notify
  // preference; the fixtures are all terminal-on-mount or non-terminal, so the signal never
  // fires here (a shared-link terminal job is not a transition).
  return render(
    <QueryClientProvider client={client}>
      <NotifyPreferenceProvider>
        <ConversionJobPage />
      </NotifyPreferenceProvider>
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

  it("renders a paused job as the interactive recovery step, one card per scenario", async () => {
    renderWithEnvelope(awaitingJob);
    expect(await screen.findByTestId("recovery-step")).toBeInTheDocument();
    expect(screen.getAllByTestId("decision-card")).toHaveLength(2);
    // The v0.6 read-only placeholder is gone — decisions are made here, not pointed at the API.
    expect(screen.queryByTestId("awaiting-recovery")).not.toBeInTheDocument();
  });

  it("does not apply the single-file cards to a batch parent", async () => {
    renderWithEnvelope(batchCompletedJob);
    await screen.findByRole("heading", { name: "Batch conversion" });
    // No conversion report panel, no "completed but carried no conversion report" fallback, no
    // single-file cancel wording — the batch branch owns this record.
    expect(screen.queryByRole("region", { name: /conversion report/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Completed" })).not.toBeInTheDocument();
  });

  it("offers a first-class decline within the step, not only the page footer", async () => {
    renderWithEnvelope(awaitingJob);
    const decline = await screen.findByRole("button", { name: /cancel conversion/i });
    expect(decline).toBeInTheDocument();
    // The paused step supersedes the footer cancel — one decline, inside the decision surface.
    expect(screen.queryByRole("button", { name: /cancel this conversion/i })).not.toBeInTheDocument();
  });

  it("hands a completed job off to its durable record, where the download lives", async () => {
    renderWithEnvelope(completedJob);
    const link = await screen.findByRole("link", { name: /view the full record/i });
    expect(link).toHaveAttribute("href", `/conversions/${completedJob.result.conversion_id}`);
    // The job page itself offers no download — the record page puts it below the loss summary.
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });

  it("offers no Cancel once the job is terminal", async () => {
    renderWithEnvelope(cancelledJob);
    await screen.findByRole("region", { name: /cancelled/i });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /cancel this conversion/i })).toBeNull(),
    );
  });
});

describe("ConversionJobPage batch record (v1.5 M58-S2)", () => {
  it("renders a completed batch as parent tallies above per-file links, never an invented report", async () => {
    renderWithEnvelope(batchCompletedJob);
    // The page names the batch honestly — a batch record, not a single conversion.
    expect(await screen.findByRole("heading", { name: "Batch conversion" })).toBeInTheDocument();

    // The tallies are the service's own counts, rendered as-is: 2 files, 1 converted, 1 refused.
    const tallies = screen.getByRole("region", { name: "Batch result" });
    expect(tallies).toHaveTextContent("Total");
    expect(tallies).toHaveTextContent("2");
    expect(tallies).toHaveTextContent("Converted");
    expect(tallies).toHaveTextContent("Refused");
    expect(tallies).toHaveTextContent("Failed");
    expect(tallies).toHaveTextContent("energy ×0");

    // Per-file links resolve to the ordinary child records (converted + refused in order), each on
    // its own file's workspace Convert tab (the child's live `file_id`, UI redesign S2).
    const [converted, refused] = batchCompletedJob.result.entries;
    const links = screen.getAllByRole("link", { name: /view this file\u2019s conversion record/i });
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute(
      "href",
      `/f/${converted.file_id}/convert?job=${converted.child_job_id}`,
    );
    expect(links[1]).toHaveAttribute(
      "href",
      `/f/${refused.file_id}/convert?job=${refused.child_job_id}`,
    );
    // The batch itself offers no download — each file's download lives on its own record.
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });

  it("renders a paused batch as waiting on the child records, with no recovery block of its own", async () => {
    renderWithEnvelope(batchAwaitingJob);
    const card = await screen.findByRole("region", { name: "Waiting on a decision" });
    // The batch made no choice; the decision belongs to the paused child's own record.
    expect(card).toHaveTextContent(/made no choice for any file/i);

    const child = batchAwaitingJob.children[0];
    expect(child.state).toBe("awaiting_recovery");
    const answer = screen.getByRole("link", { name: /answer on this conversion's record/i });
    expect(answer).toHaveAttribute(
      "href",
      `/f/${child.file_id}/convert?job=${child.job_id}`,
    );
    // The batch parent carries no recovery step of its own — nothing to decide here.
    expect(screen.queryByTestId("recovery-step")).not.toBeInTheDocument();
  });
});
