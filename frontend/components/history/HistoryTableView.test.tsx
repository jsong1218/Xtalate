import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HistoryTableView } from "./HistoryTableView";
import type { HistoryItem } from "@/lib/history/status";
import sample from "./__fixtures__/history.sample.json";

/**
 * The history table renders **exactly what `GET /v1/history` returns** (slice M33-S2). The fixture
 * spans every state the deliverable names — completed×{passed,failed}, refused, and the expired
 * state (a live *and* a gone `file_id`) — and these tests assert each renders, loss is visible even
 * in a row, and the **expired-bytes honesty** holds: an expired row keeps a readable-report path
 * while its re-convert/delete affordances fall away with a stated reason, never a dead button or a
 * surprise 410.
 */
const items = (sample as unknown as { items: HistoryItem[] }).items;

function row(conversionId: string): HTMLElement {
  return screen.getByTestId(`history-row-${conversionId}`);
}

function renderView(overrides: Partial<Parameters<typeof HistoryTableView>[0]> = {}) {
  return render(
    <HistoryTableView
      items={items}
      hasMore={true}
      onLoadMore={vi.fn()}
      loadingMore={false}
      retention={{ uploadHours: 24, reportDays: 30 }}
      onFileDeleted={vi.fn()}
      {...overrides}
    />,
  );
}

describe("HistoryTableView (Part 7 §2.6, generated from /v1/history)", () => {
  it("renders every status combination plus the expired state without dropping a row", () => {
    renderView();
    for (const item of items) {
      expect(row(item.conversion_id)).toBeInTheDocument();
    }
  });

  it("shows each row's status in the §4 vocabulary — refused, failed, converted", () => {
    renderView();
    expect(within(row("conv-refused")).getByText("Refused")).toBeInTheDocument();
    expect(within(row("conv-completed-fail")).getByText("Validation failed")).toBeInTheDocument();
    expect(within(row("conv-completed-pass")).getByText("Converted")).toBeInTheDocument();
  });

  it("makes loss visible even at row granularity — the summary chips are in the row", () => {
    renderView();
    const failRow = row("conv-completed-fail");
    expect(within(failRow).getByText("5 fields removed")).toBeInTheDocument();
    expect(within(failRow).getByText("8 fields preserved")).toBeInTheDocument();
  });

  it("names the source → target formats per row", () => {
    renderView();
    const r = row("conv-completed-pass");
    expect(within(r).getByText("extxyz")).toBeInTheDocument();
    expect(within(r).getByText("cif")).toBeInTheDocument();
  });

  it("offers open-record, re-convert, and delete on a row whose upload is still live", () => {
    renderView();
    const r = row("conv-completed-pass");
    // Open record threads the live `file_id` forward (F7), so a refused record reached from here can
    // resolve-and-retry the upload that is demonstrably still alive rather than degrading to a fresh
    // upload prompt.
    expect(within(r).getByRole("link", { name: /open record/i })).toHaveAttribute(
      "href",
      "/conversions/conv-completed-pass?file_id=file-1",
    );
    expect(within(r).getByRole("link", { name: /re-?convert/i })).toHaveAttribute(
      "href",
      "/files/file-1",
    );
    expect(within(r).getByRole("button", { name: /delete file/i })).toBeInTheDocument();
  });

  it("keeps the report readable on an expired row while honestly dropping re-convert and delete", () => {
    renderView();
    const r = row("conv-expired");
    // The report survives the bytes: open-record still resolves — bare, with no `file_id` to thread.
    expect(within(r).getByRole("link", { name: /open record/i })).toHaveAttribute(
      "href",
      "/conversions/conv-expired",
    );
    // Re-convert and delete are gone (no live source), replaced by a stated reason — not dead buttons.
    expect(within(r).queryByRole("link", { name: /re-?convert/i })).not.toBeInTheDocument();
    expect(within(r).queryByRole("button", { name: /delete file/i })).not.toBeInTheDocument();
    expect(within(r).getByText(/source file expired/i)).toBeInTheDocument();
  });

  it("paginates by the server cursor — a Load more control appears and fires", () => {
    const onLoadMore = vi.fn();
    renderView({ onLoadMore });
    const button = screen.getByRole("button", { name: /load more/i });
    fireEvent.click(button);
    expect(onLoadMore).toHaveBeenCalled();
  });

  it("shows no Load more control on the last page", () => {
    renderView({ hasMore: false });
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
  });
});
