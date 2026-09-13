import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalysisResults } from "./AnalysisResults";

/**
 * The generic analysis renderer (MASTER_SPEC Part 7 §6; v1.8 M70). It is a *type-driven* walk over
 * the plugin's namespaced results — scalar, object, array, and the null-with-a-note case — with
 * **zero plugin-specific branching**: it never mentions "composition" or any key by name, so a
 * third-party analysis plugin renders through the same path. These tests drive it with the
 * composition plugin's real result shape (a scalar formula, an element-count object, a null density
 * paired with its plain-language note) precisely to prove the generic walk covers a real plugin, and
 * separately assert the honest `status: "error"` failure path.
 */

describe("AnalysisResults", () => {
  it("renders a scalar, an object, an array, and a null paired with its note", () => {
    render(
      <AnalysisResults
        pluginName="composition"
        results={{
          "composition:formula": "H2O",
          "composition:element_counts": { H: 2, O: 1 },
          "composition:atom_count": 3,
          "composition:some_series": [1, 2, 3],
          "composition:mass_density_g_per_cm3": null,
          "composition:density_note":
            "mass density not computed: no simulation cell declared in the source",
        }}
      />,
    );

    // A scalar renders its value verbatim.
    expect(screen.getByText("H2O")).toBeInTheDocument();
    // The object's entries render (a key/value pair inside a nested table).
    expect(screen.getByText("H")).toBeInTheDocument();
    // A null value is an honest "not computed", never a dropped row (P1, P3)...
    expect(screen.getByText("not computed")).toBeInTheDocument();
    // ...and the plugin's plain-language sibling note renders as its own annotated row.
    expect(screen.getByText(/no simulation cell declared/i)).toBeInTheDocument();
    // The raw namespaced key is preserved somewhere for an operator to match against the wire.
    expect(
      screen.getByTitle("composition:mass_density_g_per_cm3"),
    ).toBeInTheDocument();
  });

  it("humanizes the label but keeps the raw key in a title", () => {
    render(
      <AnalysisResults
        pluginName="composition"
        results={{ "composition:atom_count": 3 }}
      />,
    );
    // Label drops the "<plugin>:" namespace and the underscores.
    const row = screen.getByTitle("composition:atom_count");
    expect(within(row).getByText(/atom count/i)).toBeInTheDocument();
  });

  it("renders the honest failure reason for a status:error result", () => {
    render(
      <AnalysisResults
        pluginName="badns"
        status="error"
        message="plugin 'badns' wrote an out-of-namespace key"
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/out-of-namespace/)).toBeInTheDocument();
  });

  it("renders an empty-results run as an explicit 'no results' note, not a blank panel", () => {
    render(<AnalysisResults pluginName="quiet" results={{}} />);
    expect(screen.getByText(/no results/i)).toBeInTheDocument();
  });
});
