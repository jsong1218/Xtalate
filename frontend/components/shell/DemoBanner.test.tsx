import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DemoBanner } from "./DemoBanner";

/**
 * The public-demo banner (v1.1 M39-S1) is env-flagged: it exists so the hosted demo
 * states its ephemeral posture up front, and it must be **absent** everywhere else — a self-host
 * must never render "Public demo". The two load-bearing invariants, each a test:
 *  1. flag-off → nothing renders, and the limits query never fires (the demo-only surface must not
 *     add a request to ordinary instances — the query is `enabled`-gated on the flag).
 *  2. flag-on → the banner renders, with the cap read from the *running instance's* `/v1/limits`
 *     (never a hard-coded number — the same dynamic value the landing page and upload dropzone
 *     use), and the escape hatch to the free local path.
 */

// vi.mock factories are hoisted above top-level consts, so the shared fn must be created with
// vi.hoisted (the repo's convention for module mocks with shared fns).
const { getLimits } = vi.hoisted(() => ({ getLimits: vi.fn() }));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    apiClient: { GET: getLimits },
  };
});

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  getLimits.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("DemoBanner", () => {
  it("renders nothing when the demo flag is off, and makes no limits request", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    render(<DemoBanner />, { wrapper });
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
    expect(getLimits).not.toHaveBeenCalled();
  });

  it("renders the demo posture with the instance's live cap when the flag is on", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "1");
    getLimits.mockResolvedValue({
      data: { max_upload_bytes: 26_214_400 },
      error: undefined,
    });

    render(<DemoBanner />, { wrapper });

    expect(await screen.findByTestId("demo-banner")).toBeInTheDocument();
    // The ephemeral posture is stated up front, not discovered by hitting a limit.
    expect(screen.getByTestId("demo-banner")).toHaveTextContent("Public demo");
    expect(screen.getByTestId("demo-banner")).toHaveTextContent(/data is not retained/i);
    // The cap is the running instance's value (26_214_400 bytes → "25 MB"), never a literal.
    // find* the cap itself: the banner's first render (query still in flight) legitimately omits it.
    expect(await screen.findByText(/25 MB upload cap/)).toBeInTheDocument();
    // The funnel to the free local path (the same escape hatch as the 413 path).
    expect(screen.getByRole("link", { name: /install the CLI or self-host/i })).toHaveAttribute(
      "href",
      "/docs/self-hosting",
    );
  });

  it("renders the posture without a cap clause when /v1/limits errors — never a fake number", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "1");
    getLimits.mockRejectedValue(new Error("backend unreachable"));

    render(<DemoBanner />, { wrapper });

    expect(await screen.findByTestId("demo-banner")).toHaveTextContent("Public demo");
    // The cap clause is omitted, not guessed: the text must not name any byte figure.
    expect(screen.getByTestId("demo-banner")).not.toHaveTextContent(/MB upload cap/);
  });
});
