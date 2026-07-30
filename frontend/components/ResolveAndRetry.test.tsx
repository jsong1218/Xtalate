import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ResolveAndRetry } from "./ResolveAndRetry";
import refusedRecord from "@/components/__fixtures__/conversion.record.refused.json";
import type { ConversionRecord } from "@/lib/report/types";

/**
 * "Resolve and retry" from a refused record (MASTER_SPEC Part 7; slice M32-S2).
 *
 * A refused conversion's record is **immutable history** — but a `RECOVERY_REQUIRED` refusal is not a
 * dead-end: the same file and target can be re-submitted *with interactive recovery*, so the very
 * scenarios that were unresolved reappear as M31 decision cards. The load-bearing rules:
 *
 *  1. It is a **fresh `POST /v1/convert`** for the same `file_id` + `target_format_id` — never a
 *     mutation of the refused row (standing rule 1). The refused record's `conversion_id` is never
 *     sent; new history is created.
 *  2. The retry is only offered while the **source upload is still in hand** (a `file_id` threaded
 *     forward). Absent that, the honest path is a fresh upload, not a link that would 404.
 *  3. A refusal with **no unresolved scenarios** (e.g. `UNACKNOWLEDGED_LOSS`) offers no retry — there
 *     are no cards to re-enter, so a "resolve" button would be a lie.
 */

const submitConvert = vi.fn();
vi.mock("@/lib/api/queries", () => ({
  submitConvert: (...args: unknown[]) => submitConvert(...args),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const refused = refusedRecord as unknown as ConversionRecord;

/** A refusal that carries no unresolved scenarios — the UNACKNOWLEDGED_LOSS shape. */
const lossRefusal = {
  ...refused,
  conversion_report: {
    ...refused.conversion_report,
    refusal: {
      code: "UNACKNOWLEDGED_LOSS",
      message: "strict mode: reductive loss was not acknowledged",
      unresolved_scenarios: [],
    },
  },
} as unknown as ConversionRecord;

beforeEach(() => {
  submitConvert.mockReset();
  push.mockReset();
});

describe("ResolveAndRetry", () => {
  it("offers to re-enter the decisions when the source upload is still in hand", () => {
    render(<ResolveAndRetry record={refused} fileId="file-123" />);
    expect(screen.getByRole("button", { name: /resolve and retry/i })).toBeEnabled();
  });

  it("re-submits the same file and target with recovery, then routes to the new job carrying the file_id", async () => {
    submitConvert.mockResolvedValue({ ok: true, envelope: { job_id: "job-new" } });
    render(<ResolveAndRetry record={refused} fileId="file-123" />);

    fireEvent.click(screen.getByRole("button", { name: /resolve and retry/i }));

    await waitFor(() => expect(submitConvert).toHaveBeenCalled());
    // Same file and same target — never the refused record's own id (that row is immutable).
    expect(submitConvert).toHaveBeenCalledWith("file-123", "poscar");
    expect(submitConvert.mock.calls[0]).not.toContain(refused.conversion_id);
    // The new job carries the file_id forward so its record can offer this action again.
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/convert/job-new?file_id=file-123"),
    );
  });

  it("falls back to a fresh upload when the source upload is not in hand", () => {
    render(<ResolveAndRetry record={refused} fileId={null} />);
    // No re-submit is possible without the file, so no button that would 404.
    expect(screen.queryByRole("button", { name: /resolve and retry/i })).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: /upload the file again/i });
    expect(link).toHaveAttribute("href", "/convert");
    expect(submitConvert).not.toHaveBeenCalled();
  });

  it("offers nothing for a refusal with no unresolved scenarios", () => {
    const { container } = render(<ResolveAndRetry record={lossRefusal} fileId="file-123" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the service error envelope verbatim if the re-submission fails", async () => {
    submitConvert.mockResolvedValue({
      ok: false,
      error: { error: { code: "UPLOAD_EXPIRED", message: "The uploaded file has expired." } },
    });
    render(<ResolveAndRetry record={refused} fileId="file-123" />);

    fireEvent.click(screen.getByRole("button", { name: /resolve and retry/i }));

    expect(await screen.findByText("UPLOAD_EXPIRED")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
