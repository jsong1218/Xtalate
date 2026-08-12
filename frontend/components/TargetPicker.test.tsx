import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TargetPicker } from "./TargetPicker";
import { writableTargets, type CapabilitiesMap } from "@/lib/capabilities/types";
import type { DiscoveryReport } from "@/lib/report/types";
import capabilitiesFixture from "@/lib/capabilities/__fixtures__/capabilities.json";
import extxyzDiscovery from "@/lib/discovery/__fixtures__/discovery.extxyz.json";

/**
 * Target picker + pre-flight overlay (MASTER_SPEC Part 3 §4.3, Part 7 §2). Real `capabilities --json`
 * and `inspect --json` fixtures throughout, so the grid and the overlay reflect the actual writable
 * formats and the actual extXYZ→POSCAR intersection.
 */

const targets = writableTargets(capabilitiesFixture as unknown as CapabilitiesMap);
const discovery = extxyzDiscovery as unknown as DiscoveryReport;

const renderPicker = (onConvert = vi.fn()) => {
  render(<TargetPicker discovery={discovery} targets={targets} onConvert={onConvert} />);
  return onConvert;
};

describe("TargetPicker (Part 3 §4.3)", () => {
  it("renders a button for every write-capable format and no overlay until one is chosen", () => {
    renderPicker();
    expect(screen.getByRole("button", { name: "VASP POSCAR" })).toBeInTheDocument();
    expect(screen.queryByTestId("preflight-overlay")).not.toBeInTheDocument();
  });

  it("overlays the carry / drop / recover prediction when a target is selected", () => {
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));

    const carry = screen.getByRole("region", { name: "Will carry" });
    // lattice is present in the source and POSCAR-writable → it carries, it does not "need recovery".
    expect(within(carry).getByText("Simulation cell (lattice vectors)")).toBeInTheDocument();

    const drop = screen.getByRole("region", { name: "Will drop" });
    expect(within(drop).getByText("Atom masses")).toBeInTheDocument();

    const recover = screen.getByRole("region", { name: "Will need recovery" });
    // extXYZ has cell + species, and one frame → POSCAR needs nothing recovered.
    expect(within(recover).getByText("No recovery needed.")).toBeInTheDocument();
  });

  it("opens an explicit confirm step before converting — no POST on the first click (B2)", () => {
    // v1.1 M39-S4 B2: clicking "Convert to …" must NOT submit. The confirm card appears, reusing
    // the pre-flight preview as its content, with a final Convert and a Cancel.
    const onConvert = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));

    fireEvent.click(screen.getByRole("button", { name: "Convert to VASP POSCAR" }));
    expect(onConvert).not.toHaveBeenCalled();

    const confirm = screen.getByTestId("convert-confirm");
    expect(within(confirm).getByRole("heading", { name: "Convert to VASP POSCAR?" })).toBeInTheDocument();
    // The confirm content is the already-computed pre-flight preview (carry/drop/recover).
    expect(within(confirm).getByTestId("preflight-overlay")).toBeInTheDocument();
    expect(within(confirm).getByText("Atom masses")).toBeInTheDocument();
    expect(within(confirm).getByRole("button", { name: "Convert" })).toBeInTheDocument();
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("Cancel returns to the picker and records nothing (B2)", () => {
    const onConvert = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));
    fireEvent.click(screen.getByRole("button", { name: "Convert to VASP POSCAR" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onConvert).not.toHaveBeenCalled();
    expect(screen.queryByTestId("convert-confirm")).not.toBeInTheDocument();
    // Back to the picker: the submit button is offered again.
    expect(screen.getByRole("button", { name: "Convert to VASP POSCAR" })).toBeInTheDocument();
  });

  it("the final Convert fires onConvert once, with the chosen target and mode (B2)", async () => {
    const onConvert = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));
    expect(screen.getByRole("radio", { name: /permissive/i })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Convert to VASP POSCAR" }));
    // Wrapped in act: the final Convert resolves onConvert then clears `submitting` in a microtask.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Convert" }));
    });
    expect(onConvert).toHaveBeenCalledTimes(1);
    expect(onConvert).toHaveBeenCalledWith("poscar", "permissive");
  });

  it("passes strict mode through when the user opts into it", async () => {
    const onConvert = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));
    fireEvent.click(screen.getByRole("radio", { name: /strict/i }));
    fireEvent.click(screen.getByRole("button", { name: "Convert to VASP POSCAR" }));
    // The confirm card names the locked-in mode before the final commit.
    expect(screen.getByTestId("convert-confirm")).toHaveTextContent(/Mode: Strict/);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Convert" }));
    });
    expect(onConvert).toHaveBeenCalledTimes(1);
    expect(onConvert).toHaveBeenCalledWith("poscar", "strict");
  });

  it("disables the final Convert while its submit is in flight, so a double-click cannot record twice (B2)", async () => {
    let release: () => void = () => {};
    const onConvert = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
    renderPicker(onConvert);
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));
    fireEvent.click(screen.getByRole("button", { name: "Convert to VASP POSCAR" }));
    fireEvent.click(screen.getByRole("button", { name: "Convert" }));
    // While the POST is pending the button reports the in-flight state and is disabled, so a second
    // click is a no-op — no second /v1/convert, no second record.
    const converting = screen.getByRole("button", { name: "Converting…" });
    expect(converting).toBeDisabled();
    fireEvent.click(converting);
    expect(onConvert).toHaveBeenCalledTimes(1);
    // Settle the pending promise so the trailing `submitting` reset flushes inside act.
    await act(async () => {
      release();
    });
  });
});
