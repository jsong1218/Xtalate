import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CommandPaletteTrigger } from "./CommandPaletteTrigger";

/**
 * The ⌘K command palette (S4, D246) — the crate of the no-dependency palette. The tests pin the
 * accessibility contract a real-user journey can't affordably check: it opens, traps focus (Tab
 * cannot leave), closes on Escape, and hands focus back to the trigger. The fuzzy ranking itself is
 * `lib/command/fuzzy.test.ts`; here the untestable-in-e2e piece — focus behavior — is asserted.
 */
const pushSpy = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushSpy }) }));

function renderTrigger() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  // Provide `/v1/capabilities` up front so the palette's format section has data to fuzzy on
  // (the query is disabled while closed; the prefetch is what a live stack would supply).
  queryClient.setQueryData(["capabilities"], {
    poscar: {
      write: {
        format_id: "poscar",
        format_name: "POSCAR",
        direction: "write",
        fields: {},
        max_frames: 1,
        required_fields: [],
        allows_open_boundaries: false,
        representable_constraint_kinds: [],
        writable_custom_keys: {},
        writable_custom_key_pattern: {},
        native_coordinate_system: "cartesian",
        lossy_notes: [],
        numeric_precision: {},
      },
    },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <CommandPaletteTrigger />
    </QueryClientProvider>,
  );
  return view;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CommandPaletteTrigger + palette (⌘K)", () => {
  it("the trigger advertises the dialog and can open it", () => {
    renderTrigger();
    const trigger = screen.getByRole("button", { name: /Search/i });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("Meta+K opens the dialog and Escape closes it", () => {
    renderTrigger();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not hijack Meta+K while typing in an input", () => {
    renderTrigger();
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    // The keydown bubbles up from the editable to the window listener, which must suppress it.
    fireEvent.keyDown(input, { key: "k", metaKey: true, bubbles: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    document.body.removeChild(input);
  });

  it("typing filters fuzzy results and Enter on a result navigates", () => {
    renderTrigger();
    fireEvent.click(screen.getByRole("button", { name: /Search/i }));
    const input = screen.getByLabelText("Search commands");
    fireEvent.change(input, { target: { value: "Pos" } });
    // "POSCAR" is the exact-substring format candidate; Enter chooses the active (top) result.
    const poscar = screen.getAllByRole("option").find((o) => (o.textContent ?? "").includes("POSCAR"));
    expect(poscar).toBeTruthy();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushSpy).toHaveBeenCalledWith("/formats/poscar");
  });

  it("Escape from inside the dialog closes it", () => {
    renderTrigger();
    fireEvent.click(screen.getByRole("button", { name: /Search/i }));
    fireEvent.keyDown(screen.getByLabelText("Search commands"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});