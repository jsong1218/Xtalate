import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Toolbar } from "./Toolbar";
import { NotifyPreferenceProvider } from "@/lib/notify/NotifyPreferenceProvider";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";

/**
 * `Toolbar` mounts the ⌘K palette (needs the router + react-query) and the theme/notify toggles
 * (need their providers) — same setup as `AppHeader.test.tsx`, plus a `usePathname` mock (like
 * `WorkspaceTabs.test.tsx`) since the Convert verb derives its target from the active `/f/[id]`
 * route.
 */
const { usePathname, pushMock } = vi.hoisted(() => ({
  usePathname: vi.fn(() => "/"),
  pushMock: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname,
  useRouter: () => ({ push: pushMock }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  usePathname.mockReturnValue("/");
});

function renderToolbar() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <NotifyPreferenceProvider>
          <Toolbar />
        </NotifyPreferenceProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("Toolbar", () => {
  it("renders a banner landmark", () => {
    renderToolbar();
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("puts the Xtalate wordmark first, linking home", () => {
    renderToolbar();
    expect(screen.getByRole("link", { name: "Xtalate" })).toHaveAttribute("href", "/");
  });

  it("offers an Open/Upload verb pointing at the landing dropzone", () => {
    renderToolbar();
    expect(screen.getByRole("link", { name: /open.*upload/i })).toHaveAttribute("href", "/");
  });

  it("offers the global destinations in a named Primary nav", () => {
    renderToolbar();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const expected: [string, string][] = [
      ["Formats", "/formats"],
      ["History", "/history"],
      ["Docs", "/docs"],
    ];
    for (const [label, href] of expected) {
      expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("keeps the global destinations out of the left File-actions nav (design spec grouping)", () => {
    // Design spec §"Shell architecture": Formats/History/Docs belong in the RIGHT cluster
    // alongside ⌘K and the toggles, not the left verb nav next to Open/Upload and Convert.
    renderToolbar();
    const fileActions = screen.getByRole("navigation", { name: "File actions" });
    expect(within(fileActions).queryByRole("link", { name: "Formats" })).not.toBeInTheDocument();
    expect(within(fileActions).queryByRole("link", { name: "History" })).not.toBeInTheDocument();
    expect(within(fileActions).queryByRole("link", { name: "Docs" })).not.toBeInTheDocument();
    // The left nav still carries the per-file verbs.
    expect(within(fileActions).getByRole("link", { name: /open.*upload/i })).toBeInTheDocument();
  });

  it("has no duplicate unlabeled nav landmarks (two distinctly-labeled navs only)", () => {
    renderToolbar();
    const navs = screen.getAllByRole("navigation");
    expect(navs).toHaveLength(2);
    const names = navs.map((nav) => nav.getAttribute("aria-label"));
    expect(names.sort()).toEqual(["File actions", "Primary"]);
  });

  it("mounts the command-palette trigger (⌘K)", () => {
    renderToolbar();
    const trigger = screen.getByRole("button", { name: /Search/i });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
  });

  it("mounts the theme toggle", () => {
    renderToolbar();
    expect(screen.getByRole("button", { name: /switch to light mode/i })).toBeInTheDocument();
  });

  it("mounts the completion-signal mute toggle", () => {
    renderToolbar();
    expect(screen.getByRole("button", { name: "Mute completion signal" })).toBeInTheDocument();
  });

  it("disables the Convert verb when there is no active file", () => {
    usePathname.mockReturnValue("/formats");
    renderToolbar();
    const convert = screen.getByRole("button", { name: /convert/i });
    expect(convert).toBeDisabled();
  });

  it("disables the Convert verb on the landing route too", () => {
    usePathname.mockReturnValue("/");
    renderToolbar();
    expect(screen.getByRole("button", { name: /convert/i })).toBeDisabled();
  });

  it("links the Convert verb to the active file's convert route", () => {
    usePathname.mockReturnValue("/f/file-42/structure");
    renderToolbar();
    expect(screen.getByRole("link", { name: /convert/i })).toHaveAttribute(
      "href",
      "/f/file-42/convert",
    );
  });

  it("derives the active file id even when already on the convert route", () => {
    usePathname.mockReturnValue("/f/file-42/convert");
    renderToolbar();
    expect(screen.getByRole("link", { name: /convert/i })).toHaveAttribute(
      "href",
      "/f/file-42/convert",
    );
  });

  // The below-`sm` overflow "Menu" is a disclosure, not an ARIA menu (Task 13 review fix): the
  // toggle carries `aria-expanded` but no `aria-haspopup="menu"`, and the revealed verbs are plain
  // links, not `menuitem`s — so the announced semantics match the Tab-through behaviour it actually
  // implements. (jsdom does not apply the `sm:hidden` media query, so the control is in the tree.)
  describe("overflow disclosure", () => {
    it("is a disclosure button, not an ARIA menu", () => {
      renderToolbar();
      const menuButton = screen.getByRole("button", { name: "Menu" });
      expect(menuButton).toHaveAttribute("aria-expanded", "false");
      expect(menuButton).not.toHaveAttribute("aria-haspopup", "menu");
      expect(screen.queryByRole("menu")).toBeNull();
    });

    it("reveals the verbs as ordinary links and toggles closed again", () => {
      renderToolbar();
      const menuButton = screen.getByRole("button", { name: "Menu" });
      fireEvent.click(menuButton);
      expect(menuButton).toHaveAttribute("aria-expanded", "true");
      const panel = document.getElementById("toolbar-overflow-menu")!;
      expect(within(panel).getByRole("link", { name: /open.*upload/i })).toHaveAttribute(
        "href",
        "/",
      );
      expect(screen.queryByRole("menuitem")).toBeNull();
      fireEvent.click(menuButton);
      expect(document.getElementById("toolbar-overflow-menu")).toBeNull();
    });

    it("closes on an outside pointer-down", () => {
      renderToolbar();
      const menuButton = screen.getByRole("button", { name: "Menu" });
      fireEvent.click(menuButton);
      expect(document.getElementById("toolbar-overflow-menu")).not.toBeNull();
      fireEvent.mouseDown(document.body);
      expect(document.getElementById("toolbar-overflow-menu")).toBeNull();
      expect(menuButton).toHaveAttribute("aria-expanded", "false");
    });

    it("closes on Escape", () => {
      renderToolbar();
      const menuButton = screen.getByRole("button", { name: "Menu" });
      fireEvent.click(menuButton);
      expect(document.getElementById("toolbar-overflow-menu")).not.toBeNull();
      fireEvent.keyDown(document, { key: "Escape" });
      expect(document.getElementById("toolbar-overflow-menu")).toBeNull();
    });
  });
});
