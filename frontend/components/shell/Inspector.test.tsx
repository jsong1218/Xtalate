import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Inspector } from "./Inspector";

/**
 * The workbench Inspector (v2.0 addendums, Task 10; design spec §"Shell architecture" — "Inspector
 * row: Contextual: summary chips + cell + provenance (Report); atom/cell props + legend (Structure);
 * collapsible").
 *
 * This absorbs the pre-Task-9 per-file rail's inspection summary (filename, detected format +
 * confidence, present/absent field counts — `SourceRail.tsx`'s reconciliation note) as the always-on
 * content, then layers route-specific enrichment on top: SummaryChips + cell + Provenance on a
 * report route, atom/cell props + StructureLegend on a structure route.
 *
 * The transport is stubbed at the typed client (the repo convention — see `useInspection.test.tsx`),
 * dispatched by the literal endpoint path template so one mock covers inspect/job/conversion/geometry.
 */

const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn(() => "/") }));
vi.mock("next/navigation", () => ({ usePathname }));

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: (...args: unknown[]) => apiGet(...args),
    POST: (...args: unknown[]) => apiPost(...args),
  },
}));

const discoveryReport = {
  file: { filename: "sample.extxyz", size_bytes: 237, sha256: "a".repeat(64) },
  format: {
    format_id: "extxyz",
    format_name: "Extended XYZ",
    confidence: 0.9,
    overridden: false,
    ambiguous: false,
    sniff_evidence: [],
  },
  structure: { frame_count: 1, atom_count: 2, species: ["C", "O"] },
  fields: [
    { path: "atoms.symbols", status: "present", present_frames: null, format_capability: "full", detail: null },
    { path: "atoms.positions", status: "present", present_frames: null, format_capability: "full", detail: null },
    { path: "dynamics.velocities", status: "absent", present_frames: null, format_capability: "partial", detail: null },
  ],
  extras: [],
  issues: [],
  schema_version: "1.0.0",
};

const inspectJob = {
  job_id: "job_1",
  kind: "inspect",
  state: "completed",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:00Z",
  finished_at: "2026-01-01T00:00:00Z",
  expires_at: null,
  progress: { phase: "done", frames_processed: null, frames_total: null },
  awaiting_recovery: null,
  result: { discovery_report: discoveryReport },
};

const conversionRecord = {
  conversion_id: "cnv_1",
  created_at: "2026-01-01T00:00:00Z",
  source: { format_id: "extxyz", filename: "sample.extxyz" },
  target: { format_id: "xyz", filename: "output.xyz" },
  conversion_report: {
    report_id: "report_1",
    stage: "final",
    status: "completed",
    mode: "permissive",
    created_at: "2026-01-01T00:00:00Z",
    source: {
      format_id: "extxyz",
      filename: "sample.extxyz",
      sha256: "b".repeat(64),
      schema_version: "1.0.0",
    },
    target: { format_id: "xyz", filename: "output.xyz" },
    preserved: [{ path: "atoms.symbols", detail: null }],
    removed: [{ path: "atoms.masses", reason: "cannot store", detail: null }],
    supplied: [],
    assumptions: [],
    warnings: [],
    refusal: null,
  },
  validation_report: null,
  download: { available: true, requires_ack: false, filename: "output.xyz", size_bytes: 10, expires_at: null },
};

const outputGeometry = {
  cell: [
    [10, 0, 0],
    [0, 10, 0],
    [0, 0, 10],
  ],
  frame_count: 1,
  frame_index_base: 0,
  frames: [],
  source: { filename: "output.xyz", format_id: "xyz" },
  species: ["C", "O"],
};

const fileGeometry = {
  cell: null,
  frame_count: 5,
  frame_index_base: 0,
  frames: [],
  source: { filename: "sample.extxyz", format_id: "extxyz" },
  species: ["Fe", "O", "O"],
};

beforeEach(() => {
  vi.clearAllMocks();
  usePathname.mockReturnValue("/");
  window.localStorage.clear();
  apiPost.mockResolvedValue({ data: { job_id: "job_1", state: "queued" }, error: undefined });
  apiGet.mockImplementation((url: string) => {
    if (url === "/v1/jobs/{job_id}") {
      return Promise.resolve({ data: inspectJob, error: undefined });
    }
    if (url === "/v1/conversions/{conversion_id}") {
      return Promise.resolve({ data: conversionRecord, error: undefined });
    }
    if (url === "/v1/conversions/{conversion_id}/geometry") {
      return Promise.resolve({ data: outputGeometry, error: undefined });
    }
    if (url === "/v1/files/{file_id}/geometry") {
      return Promise.resolve({ data: fileGeometry, error: undefined });
    }
    return Promise.resolve({ data: undefined, error: { code: "NOT_MOCKED" } });
  });
});

function renderInspector() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Inspector />
    </QueryClientProvider>,
  );
}

describe("Inspector", () => {
  it("renders a single complementary landmark", () => {
    renderInspector();
    expect(screen.getByRole("complementary", { name: "Inspector" })).toBeInTheDocument();
  });

  it("renders nothing meaningful off a /f/ route", () => {
    usePathname.mockReturnValue("/formats");
    renderInspector();
    expect(screen.queryByTestId("inspector-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("inspector-report")).not.toBeInTheDocument();
    expect(screen.queryByTestId("inspector-structure")).not.toBeInTheDocument();
  });

  it("renders nothing meaningful on the landing route", () => {
    usePathname.mockReturnValue("/");
    renderInspector();
    expect(screen.queryByTestId("inspector-summary")).not.toBeInTheDocument();
  });

  it("shows the inspection summary for an active file: filename, format, confidence", async () => {
    usePathname.mockReturnValue("/f/file-1");
    renderInspector();
    const summary = await screen.findByTestId("inspector-summary");
    expect(within(summary).getByText("sample.extxyz")).toBeInTheDocument();
    expect(within(summary).getByText(/Extended XYZ/)).toBeInTheDocument();
    expect(within(summary).getByText(/90% confidence/)).toBeInTheDocument();
  });

  it("shows present/absent field counts from the discovery report's fields array", async () => {
    usePathname.mockReturnValue("/f/file-1");
    renderInspector();
    const summary = await screen.findByTestId("inspector-summary");
    // Fixture: 2 present (atoms.symbols, atoms.positions), 1 absent (dynamics.velocities).
    expect(within(summary).getByTestId("fields-present-count")).toHaveTextContent("2");
    expect(within(summary).getByTestId("fields-absent-count")).toHaveTextContent("1");
  });

  it("does not add report or structure enrichment on a plain file route (e.g. convert)", async () => {
    usePathname.mockReturnValue("/f/file-1/convert");
    renderInspector();
    await screen.findByTestId("inspector-summary");
    expect(screen.queryByTestId("inspector-report")).not.toBeInTheDocument();
    expect(screen.queryByTestId("inspector-structure")).not.toBeInTheDocument();
  });

  it("adds SummaryChips + Provenance on a report route", async () => {
    usePathname.mockReturnValue("/f/file-1/report/cnv_1");
    renderInspector();
    await screen.findByTestId("inspector-summary");
    const enrichment = await screen.findByTestId("inspector-report");
    expect(within(enrichment).getByLabelText("Conversion summary")).toBeInTheDocument();
    expect(within(enrichment).getByLabelText("Provenance")).toBeInTheDocument();
  });

  it("adds the conversion's output cell on a report route once its geometry loads", async () => {
    usePathname.mockReturnValue("/f/file-1/report/cnv_1");
    renderInspector();
    const enrichment = await screen.findByTestId("inspector-report");
    expect(await within(enrichment).findByTestId("inspector-cell")).toBeInTheDocument();
  });

  it("adds atom/cell props + StructureLegend on a structure route", async () => {
    usePathname.mockReturnValue("/f/file-1/structure");
    renderInspector();
    await screen.findByTestId("inspector-summary");
    const enrichment = await screen.findByTestId("inspector-structure");
    // Fixture species are per-atom [Fe, O, O] — 3 atoms, 5 frames, deduped to 2 legend rows.
    expect(within(enrichment).getByText("3")).toBeInTheDocument();
    expect(within(enrichment).getByText("5")).toBeInTheDocument();
    expect(within(enrichment).getByTestId("structure-legend")).toBeInTheDocument();
    expect(within(enrichment).getByTestId("legend-row-Fe")).toBeInTheDocument();
    expect(within(enrichment).getByTestId("legend-row-O")).toBeInTheDocument();
  });

  it("says plainly when the structure route's file declares no cell", async () => {
    usePathname.mockReturnValue("/f/file-1/structure");
    renderInspector();
    const enrichment = await screen.findByTestId("inspector-structure");
    expect(within(enrichment).getByText(/no simulation cell/i)).toBeInTheDocument();
  });

  it("exposes a collapse toggle with aria-expanded reflecting the expanded state", () => {
    renderInspector();
    const button = screen.getByRole("button", { name: /collapse inspector/i });
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("collapses on click, hiding content and flipping aria-expanded", async () => {
    usePathname.mockReturnValue("/f/file-1");
    renderInspector();
    await screen.findByTestId("inspector-summary");
    const button = screen.getByRole("button", { name: /collapse inspector/i });
    button.click();
    expect(await screen.findByRole("button", { name: /expand inspector/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByTestId("inspector-summary")).not.toBeInTheDocument();
  });

  it("completes the WAI-ARIA disclosure pattern: aria-controls names the rendered content's id", () => {
    renderInspector();
    const button = screen.getByRole("button", { name: /collapse inspector/i });
    const controlsId = button.getAttribute("aria-controls");
    expect(controlsId).toBeTruthy();
    expect(document.getElementById(controlsId as string)).toBeInTheDocument();
  });
});
