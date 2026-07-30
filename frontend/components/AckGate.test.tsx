import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AckGate } from "./AckGate";
import ackEnvelope from "@/components/__fixtures__/error.validation_ack_required.json";
import failedRecord from "@/components/__fixtures__/conversion.record.validation_failed.json";
import type { ConversionRecord } from "@/lib/report/types";

/**
 * The failed-validation acknowledgment gate (MASTER_SPEC Part 7 §2.5 item 2, Part 5 §2; slice
 * M32-S1). It **replaces** the plain download button whenever `download.requires_ack` is set — the
 * v0.6 interim let a reader click a normal "Download" button and discover the wall only when the
 * service answered `409`; the gate states the wall up front, in the engine's own words, and offers
 * no way past it that a user could take without meaning to.
 *
 * The load-bearing invariants (each a test, not an intention — IMPLEMENTATION_PLAN_v0.7 §4 rule 1):
 *  1. The failing checks are named **from the record's own Validation rows**, verbatim — not
 *     re-derived, not a second copy, and never a UI paraphrase (rule 2).
 *  2. Nothing is preselected and nothing is auto-armed: the acknowledgment starts unchecked and the
 *     download stays disabled until the reader has explicitly acknowledged.
 *  3. There is no unacknowledged path at all — no plain download button, no bare href — so the gate
 *     cannot be skipped by URL knowledge or an errant click.
 *  4. Confirming re-requests with `acknowledge_validation_failure=true` in a single deliberate act;
 *     the record is not rewritten, so the failure it records still stands afterward.
 */

const downloadOutput = vi.fn();
const saveBlob = vi.fn();
vi.mock("@/lib/api/download", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/download")>();
  return {
    ...actual,
    downloadOutput: (...args: unknown[]) => downloadOutput(...args),
    saveBlob: (...args: unknown[]) => saveBlob(...args),
  };
});

beforeEach(() => {
  downloadOutput.mockReset();
  saveBlob.mockReset();
});

const failed = failedRecord as unknown as ConversionRecord;
const failingCheck = failed.validation_report!.checks.find((c) => c.status === "fail")!;

describe("AckGate", () => {
  it("names every failed check by id and verbatim message, from the record's own rows", () => {
    render(<AckGate record={failed} />);
    const checks = screen.getByTestId("failed-checks");
    expect(checks).toHaveTextContent(failingCheck.check_id);
    // The engine's own quantitative sentence, unchanged.
    expect(checks).toHaveTextContent(failingCheck.message);
    // Only the failures are listed — a passing check is not dragged into the warning.
    const passing = failed.validation_report!.checks.find((c) => c.status === "pass")!;
    expect(checks).not.toHaveTextContent(passing.check_id);
  });

  it("states plainly what acknowledgment means", () => {
    render(<AckGate record={failed} />);
    // The Part 5 §2 access rule in the spec's own framing: taking a file that failed verification,
    // with the record continuing to say so.
    expect(screen.getByText(/failed verification/i)).toBeInTheDocument();
    expect(screen.getByText(/record (will )?(still |continue)/i)).toBeInTheDocument();
  });

  it("preselects nothing and keeps the download disabled until acknowledged", () => {
    render(<AckGate record={failed} />);
    const ack = screen.getByRole("checkbox");
    expect(ack).not.toBeChecked();
    expect(screen.getByRole("button", { name: /download the unverified file/i })).toBeDisabled();
  });

  it("offers no unacknowledged download path — no plain button and no bare href", () => {
    render(<AckGate record={failed} />);
    // The only download control names itself as unverified; there is no ordinary "Download output"
    // button that would fire an unacknowledged request the way the v0.6 interim did.
    expect(
      screen.queryByRole("button", { name: /^download output/i }),
    ).not.toBeInTheDocument();
    // And no anchor that would let the browser GET the raw download URL, bypassing the gate.
    for (const anchor of document.querySelectorAll("a")) {
      expect(anchor.getAttribute("href") ?? "").not.toContain("/v1/download/");
    }
  });

  it("downloads the unverified output only after acknowledgment, sending acknowledge=true", async () => {
    downloadOutput.mockResolvedValue({ ok: true, blob: new Blob(["x"]), filename: "output.xyz" });
    render(<AckGate record={failed} />);

    fireEvent.click(screen.getByRole("checkbox"));
    const button = screen.getByRole("button", { name: /download the unverified file/i });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(downloadOutput).toHaveBeenCalled());
    expect(downloadOutput.mock.calls[0][0]).toBe(failed.conversion_id);
    expect(downloadOutput.mock.calls[0][1]).toMatchObject({ acknowledgeValidationFailure: true });
    await waitFor(() => expect(saveBlob).toHaveBeenCalled());
  });

  it("renders the service's error envelope verbatim if the acknowledged download still fails", async () => {
    downloadOutput.mockResolvedValue({ ok: false, error: ackEnvelope });
    render(<AckGate record={failed} />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /download the unverified file/i }));
    // The stable machine code and the service's own message, unchanged.
    expect(await screen.findByText("VALIDATION_ACK_REQUIRED")).toBeInTheDocument();
    expect(screen.getByText(ackEnvelope.error.message)).toBeInTheDocument();
    // A failed acknowledged attempt never hands bytes to the browser.
    expect(saveBlob).not.toHaveBeenCalled();
  });
});
