import { fireEvent, render, screen, within } from "@testing-library/react";
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

  it("defaults to permissive mode and converts with the chosen target and mode", () => {
    const onConvert = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));

    expect(screen.getByRole("radio", { name: /permissive/i })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Convert to VASP POSCAR" }));
    expect(onConvert).toHaveBeenCalledWith("poscar", "permissive");
  });

  it("passes strict mode through when the user opts into it", () => {
    const onConvert = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: "VASP POSCAR" }));
    fireEvent.click(screen.getByRole("radio", { name: /strict/i }));
    fireEvent.click(screen.getByRole("button", { name: "Convert to VASP POSCAR" }));
    expect(onConvert).toHaveBeenCalledWith("poscar", "strict");
  });
});
