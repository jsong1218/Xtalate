import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StatusBar } from "./StatusBar";

/**
 * The workbench status bar (v2.0 addendums, Task 11; design spec §"Shell architecture" — Status bar
 * row: "file · format · atoms · frames · job state · demo/auto-expire indicator").
 *
 * Job state is deliberately **not** wired here — see `StatusBar.tsx`'s module docstring for why
 * (there is no route-independent way to reach the active job id without inventing a new fetch) — so
 * this suite only exercises the file facts + demo indicator.
 *
 * The transport is stubbed at the typed client (the repo convention — see `Inspector.test.tsx`),
 * dispatched by the literal endpoint path template so one mock covers inspect submit + job poll.
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
  structure: { frame_count: 5, atom_count: 128, species: ["C", "O"] },
  fields: [],
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

beforeEach(() => {
  vi.clearAllMocks();
  usePathname.mockReturnValue("/");
  apiPost.mockResolvedValue({ data: { job_id: "job_1", state: "queued" }, error: undefined });
  apiGet.mockImplementation((url: string) => {
    if (url === "/v1/jobs/{job_id}") {
      return Promise.resolve({ data: inspectJob, error: undefined });
    }
    return Promise.resolve({ data: undefined, error: { code: "NOT_MOCKED" } });
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

function renderStatusBar() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <StatusBar />
    </QueryClientProvider>,
  );
}

describe("StatusBar", () => {
  it("renders a single contentinfo landmark", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    renderStatusBar();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("shows a minimal ready state off a /f/ route, with no demo indicator when the flag is unset", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    usePathname.mockReturnValue("/formats");
    renderStatusBar();
    expect(screen.getByTestId("statusbar-ready")).toHaveTextContent(/ready/i);
    expect(screen.queryByTestId("statusbar-demo-indicator")).not.toBeInTheDocument();
    // A global route must never fire an inspection request.
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("never calls useInspection with a null id off a /f/ route", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    usePathname.mockReturnValue("/");
    renderStatusBar();
    expect(apiPost).not.toHaveBeenCalled();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("shows the file facts — filename, format, atom count, frame count — for an active file", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    usePathname.mockReturnValue("/f/file-1/structure");
    renderStatusBar();
    const facts = await screen.findByTestId("statusbar-facts");
    expect(within(facts).getByText("sample.extxyz")).toBeInTheDocument();
    expect(within(facts).getByText(/Extended XYZ/)).toBeInTheDocument();
    expect(within(facts).getByTestId("statusbar-atom-count")).toHaveTextContent("128");
    expect(within(facts).getByTestId("statusbar-frame-count")).toHaveTextContent("5");
  });

  it("renders the numeric facts in monospace (font-mono)", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    usePathname.mockReturnValue("/f/file-1");
    renderStatusBar();
    const facts = await screen.findByTestId("statusbar-facts");
    expect(within(facts).getByTestId("statusbar-atom-count").className).toContain("font-mono");
    expect(within(facts).getByTestId("statusbar-frame-count").className).toContain("font-mono");
  });

  it("hides the demo indicator when NEXT_PUBLIC_DEMO_BANNER is unset", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    usePathname.mockReturnValue("/f/file-1");
    renderStatusBar();
    expect(screen.queryByTestId("statusbar-demo-indicator")).not.toBeInTheDocument();
  });

  it("shows the demo indicator when NEXT_PUBLIC_DEMO_BANNER is set", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "1");
    usePathname.mockReturnValue("/f/file-1");
    renderStatusBar();
    expect(screen.getByTestId("statusbar-demo-indicator")).toBeInTheDocument();
  });
});
