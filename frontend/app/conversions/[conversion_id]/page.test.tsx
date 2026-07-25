import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

vi.mock("next/navigation", () => ({
  useParams: () => ({ conversion_id: "cnv-under-test" }),
  useSearchParams: () => new URLSearchParams(),
}));

const apiGet = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: (...args: unknown[]) => apiGet(...args),
    POST: vi.fn(async () => ({ data: undefined, error: undefined })),
  },
}));

function renderWithRecord(body: unknown) {
  apiGet.mockResolvedValue({ data: body, error: undefined });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConversionRecordPage />
    </QueryClientProvider>,
  );
}

describe("ConversionRecordPage", () => {
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
  });

  it("still serves the record once the output bytes have expired", async () => {
    renderWithRecord(expiredRecord);
    // Both reports are intact and the provenance is citable; only the bytes are gone.
    expect(await screen.findByTestId("provenance")).toBeInTheDocument();
    expect(screen.getByText(/the converted file has expired/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /re-validate/i })).toBeInTheDocument();
  });

  it("offers a fresh upload when no file_id is known, rather than a link that would 404", async () => {
    renderWithRecord(lossyRecord);
    const link = await screen.findByRole("link", { name: /convert another file/i });
    expect(link).toHaveAttribute("href", "/");
  });
});
