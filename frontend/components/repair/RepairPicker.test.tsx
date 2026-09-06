import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { RepairPicker, type RepairDraft } from "./RepairPicker";

/**
 * The repair picker (v1.7 M66-S3, D257) — the pre-conversion step where a user *asks for* repairs.
 * Two invariants are load-bearing and tested here:
 *
 *  - **The list order is the applied order.** The picker appends on add and removes in place, so
 *    the assembled `repairs` list IS the ordered list the submit sends (D255/D256 order is
 *    scientific meaning).
 *  - **The closed set of four is enumerated, never extended** (D254), and an operation whose
 *    required parameters are incomplete cannot be added — a malformed repair is a request error,
 *    never a pause.
 */

/** The picker is controlled (the page owns the list); the harness lifts state like the page does. */
function Harness({ initial = [] }: { initial?: RepairDraft[] }) {
  const [repairs, setRepairs] = useState<RepairDraft[]>(initial);
  return <RepairPicker repairs={repairs} onChange={setRepairs} />;
}

const renderPicker = (initial: RepairDraft[] = []) => render(<Harness initial={initial} />);

const selectOperation = (label: string) =>
  fireEvent.change(screen.getByTestId("repair-operation-select"), { target: { value: label } });

describe("RepairPicker", () => {
  it("offers exactly the closed set of four operations", () => {
    renderPicker();
    const options = screen.getByTestId("repair-operation-select").querySelectorAll("option");
    expect(Array.from(options).map((o) => o.getAttribute("value"))).toEqual([
      "wrap_into_cell",
      "center",
      "deduplicate",
      "species_reorder",
    ]);
  });

  it("adds a parameterless wrap_into_cell repair immediately; the same operation may repeat (order is meaning)", () => {
    renderPicker();
    fireEvent.click(screen.getByTestId("repair-add"));
    fireEvent.click(screen.getByTestId("repair-add"));
    const cards = screen.getAllByTestId("repair-card");
    expect(cards).toHaveLength(2);
    // Each card names its operation; both are wraps — a legitimate two-step request (D255).
    expect(within(cards[0]).getByText("wrap_into_cell", { exact: true })).toBeInTheDocument();
    expect(within(cards[1]).getByText("wrap_into_cell", { exact: true })).toBeInTheDocument();
    expect(within(cards[0]).getByText(/Step 1 of 2/)).toBeInTheDocument();
    expect(within(cards[1]).getByText(/Step 2 of 2/)).toBeInTheDocument();
  });

  it("won't add a center repair until reference and target are both chosen", () => {
    renderPicker();
    selectOperation("center");
    const add = screen.getByTestId("repair-add");
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByTestId("repair-center-reference"), {
      target: { value: "centroid" },
    });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByTestId("repair-center-target"), {
      target: { value: "origin" },
    });
    expect(add).toBeEnabled();
    fireEvent.click(add);
    const card = screen.getByTestId("repair-card");
    expect(within(card).getByText("reference centroid · target origin")).toBeInTheDocument();
  });

  it("won't add a deduplicate repair without a positive distance_threshold", () => {
    renderPicker();
    selectOperation("deduplicate");
    const add = screen.getByTestId("repair-add");
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByTestId("repair-dedupe-threshold"), {
      target: { value: "0.05" },
    });
    expect(add).toBeEnabled();
    fireEvent.click(add);
    const card = screen.getByTestId("repair-card");
    expect(within(card).getByText("distance_threshold 0.05")).toBeInTheDocument();
  });

  it("a zero/negative threshold is incomplete — a tolerance is a scientific judgment (P4)", () => {
    renderPicker();
    selectOperation("deduplicate");
    fireEvent.change(screen.getByTestId("repair-dedupe-threshold"), {
      target: { value: "0" },
    });
    expect(screen.getByTestId("repair-add")).toBeDisabled();
  });

  it("removing a card yields the remaining list in the same relative order", () => {
    renderPicker([
      { operation: "wrap_into_cell", parameters: {} },
      { operation: "species_reorder", parameters: {} },
    ]);
    expect(screen.getAllByTestId("repair-card")).toHaveLength(2);
    fireEvent.click(screen.getAllByTestId("repair-remove")[0]);
    const cards = screen.getAllByTestId("repair-card");
    expect(cards).toHaveLength(1);
    // The surviving card is the second one — its relative position is unchanged.
    expect(within(cards[0]).getByText("species_reorder", { exact: true })).toBeInTheDocument();
    expect(within(cards[0]).getByText(/Step 1 of 1/)).toBeInTheDocument();
  });

  it("renders an added card with the ⟳ mark and its parameters", () => {
    renderPicker([{ operation: "center", parameters: { reference: "centroid", target: "origin" } }]);
    const card = screen.getByTestId("repair-card");
    // The ⟳ "Modified on request" mark — the same vocabulary the report rows will use.
    expect(within(card).getByRole("img", { name: "Modified on request" })).toBeInTheDocument();
    expect(within(card).getByText("Center the structure")).toBeInTheDocument();
    expect(within(card).getByText("reference centroid · target origin")).toBeInTheDocument();
  });

  it("carries a description naming each operation's required parameters", () => {
    renderPicker();
    selectOperation("deduplicate");
    expect(
      screen.getByText(
        /Remove atoms closer than a distance threshold \(Å\)\. Parameter: distance_threshold\./,
      ),
    ).toBeInTheDocument();
  });
});