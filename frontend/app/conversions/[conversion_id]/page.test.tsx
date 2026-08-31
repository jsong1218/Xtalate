import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ConversionRecordPage from "./page";
import expiredRecord from "@/components/__fixtures__/conversion.record.expired.json";
import lossyRecord from "@/components/__fixtures__/conversion.record.json";
import refusedRecord from "@/components/__fixtures__/conversion.record.refused.json";

/**
 * The conversion record page (MASTER_SPEC Part 6 §4.4, Part 7 §2.5; slice M29-S2).
 *
 * The first test is the slice's non-negotiable rule and the reason the page has a fixed order at
 * all: **the download control must sit below the loss summary in the document**, so a reader cannot
 * reach the file without passing what the conversion cost. It is asserted structurally, with
 * `compareDocumentPosition`, rather than by eyeballing the JSX — a refactor that hoists the panel
 * into the header would still render, and would still be wrong.
 */

// Hoisted so the mocked `useSearchParams` returns a value tests can change per-case: the page's
// back affordance and re-convert link branch on whether a live `file_id` was handed forward.
const { urlSearchParams } = vi.hoisted(() => ({ urlSearchParams: new URLSearchParams() }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ conversion_id: "cnv-under-test" }),
  useSearchParams: () => urlSearchParams,
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: (...args: unknown[]) => apiGet(...args),
    POST: (...args: unknown[]) => apiPost(...args),
  },
}));

function renderWithRecord(body: unknown) {
  // The record GET answers with the fixture; the Structure tab's geometry GET (M60-S1) is **not**
  // under test here, so answering it with the record body would feed a fabricated "geometry" to
  // the viewer — leave it loading so the tab renders its honest loading state.
  apiGet.mockImplementation((path: unknown) => {
    if (typeof path === "string" && path.includes("/geometry")) {
      return Promise.resolve({ data: undefined, error: undefined });
    }
    return Promise.resolve({ data: body, error: undefined });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConversionRecordPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiPost.mockReset();
  apiPost.mockResolvedValue({ data: { job_id: "job-x" }, error: undefined });
  urlSearchParams.delete("file_id");
});

// The Structure tab (M60) pulls Mol*'s color-module graph into the page, so the first test in
// this file pays a heavier one-time module-init cost than the 5 s default allows.
describe(
  "ConversionRecordPage",
  () => {
  it("puts the download panel below the loss summary in the document", async () => {
    renderWithRecord(lossyRecord);
    const chips = await screen.findByTestId("summary-chips");
    const download = await screen.findByTestId("download-panel");
    // DOCUMENT_POSITION_FOLLOWING: the download panel comes *after* the chips.
    expect(chips.compareDocumentPosition(download) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // And the chips themselves are below the outcome header.
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.compareDocumentPosition(chips) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("states the outcome quantitatively, without celebrating a lossy conversion", async () => {
    renderWithRecord(lossyRecord);
    const heading = await screen.findByRole("heading", { level: 1 });
    const removed = lossyRecord.conversion_report.removed.length;
    if (removed > 0) {
      expect(heading).toHaveTextContent(new RegExp(`${removed} fields? removed`, "i"));
    } else {
      expect(heading).toHaveTextContent(/nothing was lost or assumed/i);
    }
    // No success language that could outrank the numbers.
    expect(heading).not.toHaveTextContent(/success|done!|complete!/i);
  });

  it("renders both reports side by side on a wide screen and stacked on a narrow one", async () => {
    renderWithRecord(lossyRecord);
    const columns = await screen.findByTestId("report-columns");
    // One column by default (mobile), two from the `lg` breakpoint up.
    expect(columns.className).toMatch(/grid-cols-1/);
    expect(columns.className).toMatch(/lg:grid-cols-2/);
    expect(screen.getByRole("heading", { name: /^conversion report$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^validation report$/i })).toBeInTheDocument();
  });

  it("routes a refused conversion here and renders it as a refusal, not an error", async () => {
    renderWithRecord(refusedRecord);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      /refused — no file was written/i,
    );
    // The M27 refusal component, carrying the engine's own code.
    expect(screen.getByText(refusedRecord.conversion_report.refusal!.code)).toBeInTheDocument();
    // A refusal has no validation report, and the page says so rather than showing an empty panel.
    expect(screen.getByText(/nothing was measured/i)).toBeInTheDocument();
    // No re-validate control for a conversion that has nothing to re-threshold.
    expect(screen.queryByRole("button", { name: /re-validate/i })).not.toBeInTheDocument();
    // A refused conversion has no output bytes, so no Structure/Compare viewer surface mounts
    // (M62-S3, Rev 1.84) — the RefusalPanel is the substance.
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^structure$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^compare$/i })).not.toBeInTheDocument();
  });

  it("still serves the record once the output bytes have expired", async () => {
    renderWithRecord(expiredRecord);
    // Both reports are intact and the provenance is citable; only the bytes are gone.
    expect(await screen.findByTestId("provenance")).toBeInTheDocument();
    expect(screen.getByText(/the converted file has expired/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /re-validate/i })).toBeInTheDocument();
    // The viewer tabs remain mounted for an expired record (M62-S3, Rev 1.84): reports outlive
    // bytes, and the tabs' honest states say so — the record page is never a dead end.
    expect(screen.getByRole("tab", { name: "Structure" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Compare" })).toBeInTheDocument();
  });

  it("offers a fresh upload when no file_id is known, rather than a link that would 404", async () => {
    renderWithRecord(lossyRecord);
    const link = await screen.findByRole("link", { name: /convert another file/i });
    expect(link).toHaveAttribute("href", "/");
  });

  it("back returns to history when no file_id is known", async () => {
    renderWithRecord(lossyRecord);
    await screen.findByRole("heading", { level: 1 });
    // A shared link carries no file_id; the honest destination is the history list.
    expect(screen.getByRole("link", { name: "Back to History" })).toHaveAttribute(
      "href",
      "/history",
    );
  });

  it("back returns to the file's workspace when a live file_id was handed forward", async () => {
    urlSearchParams.set("file_id", "file-42");
    renderWithRecord(lossyRecord);
    await screen.findByRole("heading", { level: 1 });
    // Arriving from a live upload, back should return to that file's workspace — not drop the
    // file in hand (UI redesign S2: the legacy route resolves into `/f/[id]`).
    expect(screen.getByRole("link", { name: "Back to Inspection" })).toHaveAttribute(
      "href",
      "/f/file-42",
    );
  });

  it("re-validates under the tolerance profile the reader chose, not always the default", async () => {
    renderWithRecord(lossyRecord);
    // The picker offers the §4.4 named profiles; the reader picks a stricter bar deliberately.
    const picker = await screen.findByRole("combobox", { name: /tolerance profile/i });
    fireEvent.change(picker, { target: { value: "strict" } });
    fireEvent.click(screen.getByRole("button", { name: /re-validate/i }));

    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const [path, options] = apiPost.mock.calls.at(-1)! as [string, { body: Record<string, unknown> }];
    expect(path).toBe("/v1/validate");
    // The chosen profile rides the request — no silent re-threshold under a bar the user didn't pick.
    expect(options.body).toMatchObject({ tolerance_profile: "strict" });
  });

  it("turns a refused record into an entry point for a fresh, resolvable conversion", async () => {
    renderWithRecord(refusedRecord);
    // With no file_id in hand (empty search params here), the honest path is a fresh upload — but
    // the resolve-and-retry region is present, so the refusal is no longer a dead-end.
    expect(await screen.findByRole("region", { name: /resolve and retry/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upload the file again/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("does not offer resolve-and-retry on a conversion that was not refused", async () => {
    renderWithRecord(lossyRecord);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("region", { name: /resolve and retry/i })).not.toBeInTheDocument();
  });
  },
  20_000,
);
