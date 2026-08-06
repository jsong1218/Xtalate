import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FormatGuidePanel } from "./FormatGuidePanel";
import { formatGuide } from "@/lib/formats/guide";

/**
 * The editorial guide panel (frontend redesign addendum §4.5) — the human-readable half of a format
 * page, rendered beside the generated capability grid. Two behaviours matter: a known format shows
 * its real prose (summary, use cases, software, what it stores, trade-offs, limitations), and an
 * unknown format id (a plugin) shows an **honest fallback note** rather than a blank — the capability
 * grid still stands on its own, so the page stays useful for a format the guide never heard of.
 */

describe("FormatGuidePanel (Part 7 §2.7 / addendum §4.5)", () => {
  it("renders the editorial guide for a known format", () => {
    render(<FormatGuidePanel formatId="xyz" formatName="Plain XYZ" />);
    const guide = screen.getByTestId("format-guide");
    const data = formatGuide("xyz")!;

    // The summary leads; a representative item from each list is present verbatim.
    expect(within(guide).getByText(data.summary)).toBeInTheDocument();
    expect(within(guide).getByText(data.useCases[0])).toBeInTheDocument();
    expect(within(guide).getByText(data.commonSoftware[0])).toBeInTheDocument();
    expect(within(guide).getByText(data.stores[0])).toBeInTheDocument();
    expect(within(guide).getByText(data.limitations[0])).toBeInTheDocument();

    // The honest-fallback note is absent when a real guide exists.
    expect(screen.queryByTestId("format-guide-fallback")).not.toBeInTheDocument();
  });

  it("renders every list entry — no editorial content is silently dropped", () => {
    render(<FormatGuidePanel formatId="cif" formatName="Crystallographic Information File" />);
    const data = formatGuide("cif")!;
    const lists = [
      data.useCases,
      data.commonSoftware,
      data.stores,
      data.advantages,
      data.disadvantages,
      data.workflows,
      data.limitations,
    ];
    for (const list of lists) {
      for (const entry of list) {
        expect(screen.getByText(entry)).toBeInTheDocument();
      }
    }
  });

  it("shows an honest fallback for a format with no guide (a plugin), never a blank", () => {
    render(<FormatGuidePanel formatId="toyfmt" formatName="Toy Format" />);
    const fallback = screen.getByTestId("format-guide-fallback");
    // Names the format and says the guide is absent while the grid still applies — no fabrication.
    expect(within(fallback).getByText(/no extended guide/i)).toBeInTheDocument();
    expect(screen.queryByTestId("format-guide")).not.toBeInTheDocument();
  });
});
