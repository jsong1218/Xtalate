import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FormatDetail } from "./FormatDetail";
import { formatRows, type FormatRow } from "@/lib/capabilities/matrix";
import type { CapabilitiesMap } from "@/lib/capabilities/types";
import realCaps from "@/lib/capabilities/__fixtures__/capabilities.json";

/**
 * The per-format detail view (slice M33-S1): read and write declarations in full, `required_fields`
 * framed as the recovery scenarios they foreshadow ("converting into this format requires…"),
 * `max_frames`, and `lossy_notes` — all straight off the endpoint's `FormatCapabilities`, rendered
 * through the shared vocabulary. Backed by the real seven-format fixture (genuine engine output);
 * CIF is the richest case (required fields, lossy notes, conditional fields).
 */

const rows = formatRows(realCaps as unknown as CapabilitiesMap);
const cif = rows.find((r) => r.format_id === "cif")!;
const xyz = rows.find((r) => r.format_id === "xyz")!;

describe("FormatDetail (Part 7 §2.7)", () => {
  it("names the format and shows both declared directions", () => {
    render(<FormatDetail format={cif} />);
    expect(
      screen.getByRole("heading", { name: /Crystallographic Information File/i, level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Reading/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Writing/i })).toBeInTheDocument();
  });

  it("frames required_fields as 'converting into … requires', a preview of recovery", () => {
    render(<FormatDetail format={cif} />);
    const req = screen.getByRole("region", { name: /required to write/i });
    expect(within(req).getByText(/converting into .* requires/i)).toBeInTheDocument();
    // CIF requires a cell — the plain label, not the raw path.
    expect(within(req).getByText("Simulation cell (lattice vectors)")).toBeInTheDocument();
  });

  it("states the single-structure frame limit in words", () => {
    render(<FormatDetail format={cif} />);
    // CIF's max_frames is 1.
    expect(screen.getAllByText(/single structure/i).length).toBeGreaterThan(0);
  });

  it("renders the write-side lossy notes verbatim", () => {
    render(<FormatDetail format={cif} />);
    expect(screen.getByText(/no space-group symbol is emitted/i)).toBeInTheDocument();
  });

  it("shows a conditional field's caveat text (the partial notes)", () => {
    render(<FormatDetail format={cif} />);
    expect(screen.getByText(/Written as fractional _atom_site_fract/i)).toBeInTheDocument();
  });

  it("handles a format with no required fields without inventing a requirement", () => {
    // Plain XYZ requires only symbols+positions; assert we don't crash and the frame line is honest.
    render(<FormatDetail format={xyz} />);
    expect(screen.getByRole("heading", { name: /Plain XYZ/i, level: 1 })).toBeInTheDocument();
    expect(screen.getAllByText(/any number of frames/i).length).toBeGreaterThan(0);
  });

  it("renders only the directions a format declares", () => {
    const readOnly: FormatRow = { format_id: "toyfmt", format_name: "Toy Format", read: cif.read };
    render(<FormatDetail format={readOnly} />);
    expect(screen.getByRole("heading", { name: /^Reading/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^Writing/i })).not.toBeInTheDocument();
    // No write side → no "required to write" block at all.
    expect(screen.queryByRole("region", { name: /required to write/i })).not.toBeInTheDocument();
  });
});
