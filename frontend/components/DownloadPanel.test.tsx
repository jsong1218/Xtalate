import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DownloadPanel, formatBytes } from "./DownloadPanel";
import expiredRecord from "@/components/__fixtures__/conversion.record.expired.json";
import failedRecord from "@/components/__fixtures__/conversion.record.validation_failed.json";
import record from "@/components/__fixtures__/conversion.record.json";
import refusedRecord from "@/components/__fixtures__/conversion.record.refused.json";
import type { ConversionRecord } from "@/lib/report/types";

/**
 * The download panel's four states (MASTER_SPEC Part 6 §4.3; slice M29-S2).
 *
 * Every record here is a real `GET /v1/conversions/{id}` body captured from the service in-process,
 * and the `409` is the service's own envelope — so what these tests assert is what the backend
 * actually sends, not a hand-drawn approximation of it.
 *
 * The load-bearing assertions:
 *  1. A failed validation replaces the plain download with the {@link AckGate}, which names the
 *     engine's failing check **verbatim** and gates access behind an explicit acknowledgment — the
 *     unverified file stays reachable, but never by accident (the gate's own behaviour is tested in
 *     `AckGate.test.tsx`; here we assert the panel delegates to it, M32-S1).
 *  2. Expired bytes read as *expired* and say the reports survive — never as "not found".
 *  3. A refused conversion says there is no file, rather than offering a broken download.
 */

const downloadOutput = vi.fn();
vi.mock("@/lib/api/download", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/download")>();
  return {
    ...actual,
    downloadOutput: (...args: unknown[]) => downloadOutput(...args),
    saveBlob: vi.fn(),
  };
});

beforeEach(() => {
  downloadOutput.mockReset();
});

const happy = record as unknown as ConversionRecord;
const failed = failedRecord as unknown as ConversionRecord;
const expired = expiredRecord as unknown as ConversionRecord;
const refused = refusedRecord as unknown as ConversionRecord;

describe("DownloadPanel", () => {
  it("shows the filename, size and expiry for available bytes", () => {
    render(<DownloadPanel record={happy} />);
    expect(screen.getByRole("button", { name: /download output\.xyz/i })).toBeEnabled();
    expect(screen.getByText(formatBytes(happy.download.size_bytes as number))).toBeInTheDocument();
    // The lifecycle horizon is stated, so "download it later" is an informed choice.
    expect(screen.getByText(/available until/i)).toBeInTheDocument();
  });

  it("hands the fetched bytes to the browser on a clean download", async () => {
    downloadOutput.mockResolvedValue({
      ok: true,
      blob: new Blob(["x"]),
      filename: "output.xyz",
    });
    render(<DownloadPanel record={happy} />);
    fireEvent.click(screen.getByRole("button", { name: /download output\.xyz/i }));
    await waitFor(() => expect(downloadOutput).toHaveBeenCalled());
    // The first attempt never pre-acknowledges anything.
    expect(downloadOutput.mock.calls[0][1]).toMatchObject({ acknowledgeValidationFailure: false });
  });

  it("replaces the plain download with the acknowledgment gate when validation failed", () => {
    render(<DownloadPanel record={failed} />);
    // The gate states the wall up front and names the failing check verbatim (its own detail is
    // covered in AckGate.test.tsx; here we assert the panel delegates to it).
    expect(screen.getByText(/validation failed for this output/i)).toBeInTheDocument();
    const checks = screen.getByTestId("failed-checks");
    expect(checks).toHaveTextContent("positions_rmsd");
    const message = failed.validation_report!.checks.find((c) => c.status === "fail")!.message;
    expect(checks).toHaveTextContent(message);

    // There is no ordinary "Download output.xyz" button in this state — the plain download is gone,
    // replaced by an acknowledgment that starts unchecked and a download disabled until it is made.
    expect(screen.queryByRole("button", { name: /download output\.xyz/i })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(
      screen.getByRole("button", { name: /download the unverified file/i }),
    ).toBeDisabled();
  });

  it("reads expired bytes as expired, and says the record survives them", () => {
    render(<DownloadPanel record={expired} />);
    expect(screen.getByText(/the converted file has expired/i)).toBeInTheDocument();
    expect(screen.getByText(/the record itself has not expired/i)).toBeInTheDocument();
    // No download control is offered for bytes that are gone.
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument();
  });

  it("says a refused conversion has no file, rather than offering a broken download", () => {
    render(<DownloadPanel record={refused} />);
    expect(screen.getByText(/there is no file to download/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });
});
