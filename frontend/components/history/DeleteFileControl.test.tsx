import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeleteFileControl } from "./DeleteFileControl";

/**
 * Deleting an uploaded source file is guarded by a confirmation that **names the retention policy in
 * plain words** (slice M33-S2) — a user should understand, before confirming, that the bytes go now
 * but the conversion report stays readable (reports-outlive-bytes). The confirmation is not a bare
 * "Are you sure?": it states what survives and what the automatic windows would otherwise be.
 */
const { deleteFile } = vi.hoisted(() => ({ deleteFile: vi.fn() }));
vi.mock("@/lib/api/queries", () => ({ deleteFile }));

describe("DeleteFileControl (Part 6 §4.3, delete-with-retention)", () => {
  beforeEach(() => {
    deleteFile.mockReset();
  });

  it("does not delete on the first click — it asks first, naming the policy", () => {
    render(
      <DeleteFileControl
        fileId="file-1"
        retention={{ uploadHours: 24, reportHours: null, reportDays: 30 }}
        onDeleted={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));

    // The confirmation names the policy and promises the report survives — in plain words.
    expect(screen.getByText(/report stays readable/i)).toBeInTheDocument();
    expect(screen.getByText(/30 days/i)).toBeInTheDocument();
    expect(deleteFile).not.toHaveBeenCalled();
  });

  it("names a sub-day report window in hours (the hosted-demo posture)", () => {
    render(
      <DeleteFileControl
        fileId="file-1"
        retention={{ uploadHours: 1, reportHours: 1, reportDays: null }}
        onDeleted={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));

    // Hours win over days: the demo's 1-hour window is stated as hours, never a stale "days".
    expect(screen.getByText(/reports for 1 h/i)).toBeInTheDocument();
    expect(screen.queryByText(/days/i)).not.toBeInTheDocument();
  });

  it("cancels without deleting", () => {
    render(<DeleteFileControl fileId="file-1" retention={null} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(deleteFile).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /delete file/i })).toBeInTheDocument();
  });

  it("deletes on confirm and notifies the parent so the list re-reads from the server", async () => {
    const onDeleted = vi.fn();
    deleteFile.mockResolvedValue({ ok: true });
    render(
      <DeleteFileControl
        fileId="file-7"
        retention={{ uploadHours: 24, reportHours: null, reportDays: 30 }}
        onDeleted={onDeleted}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleteFile).toHaveBeenCalledWith("file-7"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  });

  it("surfaces a delete failure instead of pretending it worked", async () => {
    const onDeleted = vi.fn();
    deleteFile.mockResolvedValue({ ok: false, error: { error: { message: "boom" } } });
    render(
      <DeleteFileControl
        fileId="file-7"
        retention={{ uploadHours: 24, reportHours: null, reportDays: 30 }}
        onDeleted={onDeleted}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /delete file/i }));
    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(screen.getByText(/could not be deleted/i)).toBeInTheDocument());
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
