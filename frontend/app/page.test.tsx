import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LandingPage from "./page";

/**
 * The landing (`/`) workbench empty state (v2.0 addendums, Task 12; design spec §"Empty state
 * (demo front door)"). This replaces the old scroll-style marketing page's own test coverage (there
 * was none — the page had no dedicated test before this task) with assertions for the front door's
 * load-bearing pieces:
 *
 *  - the dropzone and the "Try a sample" region are both present and reachable;
 *  - the sample tiles carry **no emoji glyphs** — the design explicitly rejected emoji here (a
 *    monochrome SVG + plain-text format badge instead, `components/samples/SamplePicker.tsx`);
 *  - the runtime `/v1/capabilities` + `/v1/limits` figures render from whatever the mocked
 *    transport returns, never a baked build-time value (the whole reason `loadOverview()` is a
 *    server-side fetch under `export const dynamic = "force-dynamic"`).
 *
 * `LandingPage` is an async Server Component (a plain async function under the Next app router), so
 * it is invoked directly and awaited before `render`, the same way a routed page composes it at
 * request time — no extra harness needed.
 */

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const apiGet = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiClient: { GET: (...args: unknown[]) => apiGet(...args) },
}));

// A rough but sufficient emoji detector for the "no emoji glyphs" assertion: the Unicode ranges
// emoji live in (pictographs, emoticons, transport/map symbols, dingbats, supplemental symbols, and
// the variation-selector/ZWJ machinery that stitches multi-codepoint emoji together).
//
// The `\u{2600}-\u{27BF}` "dingbats/misc symbols" block is the trap here: it also contains the §4
// loss-vocabulary's own glyphs — ✓ U+2713, ✕ U+2715, ✗ U+2717, ⚠ U+26A0, ⟳ U+27F3 (◆ U+25C6 sits
// outside this block, in Geometric Shapes, so it needs no carve-out). Those five codepoints are
// explicitly excluded via the lookahead below, so this is a genuine emoji-only check — it would
// still catch a real emoji if one ever crept into the sample tiles, and it would *not* false-fail if
// a vocabulary glyph ever legitimately appeared in the same subtree.
// eslint-disable-next-line no-misleading-character-class -- intentional: matching emoji code points, not a single grapheme
const EMOJI_PATTERN =
  /[\u{1F300}-\u{1FAFF}]|(?:(?!\u{2713}|\u{2715}|\u{2717}|\u{26A0}|\u{27F3})[\u{2600}-\u{27BF}])|[\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]|\u{FE0F}|\u{200D}/u;

function mockGet(path: string): unknown {
  if (path === "/v1/capabilities") {
    return { data: { xyz: {}, extxyz: {}, poscar: {} }, error: undefined };
  }
  if (path === "/v1/limits") {
    return {
      data: {
        max_upload_bytes: 25 * 1024 * 1024,
        upload_retention_hours: 24,
        output_retention_hours: 24,
      },
      error: undefined,
    };
  }
  if (path === "/v1/history") {
    return { data: { items: [], next_cursor: null }, error: undefined };
  }
  return { data: undefined, error: { code: "NOT_MOCKED" } };
}

async function renderLanding() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  const page = await LandingPage();
  return render(<QueryClientProvider client={queryClient}>{page}</QueryClientProvider>);
}

describe("LandingPage (workbench empty state)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    apiGet.mockImplementation(async (path: string) => mockGet(path));
  });

  it("shows the dropzone", async () => {
    await renderLanding();
    expect(screen.getByLabelText("Choose a file to convert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose a file" })).toBeInTheDocument();
  });

  it("shows a 'Try a sample' region with the three vendored samples", async () => {
    await renderLanding();
    const region = screen.getByRole("region", { name: "Try a sample" });
    expect(region).toBeInTheDocument();
    expect(screen.getByTestId("sample-water")).toBeInTheDocument();
    expect(screen.getByTestId("sample-diatomic")).toBeInTheDocument();
    expect(screen.getByTestId("sample-nacl")).toBeInTheDocument();
  });

  it("renders no emoji glyphs anywhere in the sample tiles", async () => {
    await renderLanding();
    const picker = screen.getByTestId("sample-picker");
    expect(EMOJI_PATTERN.test(picker.textContent ?? "")).toBe(false);
  });

  it("the emoji guard itself still catches real emoji but not the §4 loss-vocabulary glyphs", () => {
    // Proves the pattern above is a genuine emoji-only check, not one that merely happens to pass
    // because the sample-picker subtree contains no vocabulary glyphs today.
    expect(EMOJI_PATTERN.test("🎉")).toBe(true);
    expect(EMOJI_PATTERN.test("Try it \u{1F9EA} now")).toBe(true);
    expect(EMOJI_PATTERN.test("✓ ✕ ✗ ⚠ ◆ ⟳")).toBe(false);
  });

  it("folds the loss vocabulary into a compact legend near the dropzone", async () => {
    await renderLanding();
    const legend = screen.getByLabelText("Loss vocabulary");
    expect(legend).toHaveTextContent("Preserved");
    expect(legend).toHaveTextContent("Dropped");
    expect(legend).toHaveTextContent("Assumed");
    expect(legend).toHaveTextContent("Warned");
  });

  it("renders the runtime format count and size cap from the mocked transport, not a baked value", async () => {
    await renderLanding();
    // 3 formats from the mocked /v1/capabilities payload above; 25 MB from the mocked /v1/limits.
    // The dropzone (UploadDropzone) renders its own, separately-worded size-cap line, so the exact
    // full sentence is asserted here to land on this page-level figure specifically.
    expect(
      screen.getByText("3 formats supported · files up to 25 MB on this instance."),
    ).toBeInTheDocument();
  });

  it("omits the live figures rather than faking them when the transport fails", async () => {
    apiGet.mockImplementation(async () => {
      throw new Error("network down");
    });
    await renderLanding();
    expect(screen.queryByText(/formats supported/)).not.toBeInTheDocument();
    // The page still renders its primary action even with the API unreachable.
    expect(screen.getByRole("link", { name: "Convert a file" })).toBeInTheDocument();
  });
});
