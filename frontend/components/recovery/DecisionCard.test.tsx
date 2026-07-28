import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DecisionCard } from "./DecisionCard";
import type { AwaitingScenario } from "@/lib/report/types";

/**
 * The decision card (M31-S1, Part 7 §3.1–3.2). The card turns one unresolved scenario's *offered*
 * options into a choice the engine will accept — and it carries two un-cuttable invariants:
 *
 *  - **No option is ever preselected** (§3.2): a preselected radio is a default with extra steps.
 *  - **The Assumption preview is the record** (§3, P4): the sentence shown before confirming is the
 *    exact one that will be recorded, passed in from the engine's preview — never a UI paraphrase.
 */

const lattice: AwaitingScenario = {
  scenario: "missing_lattice",
  path: "cell.lattice_vectors",
  detail: "target requires cell.lattice_vectors, absent on source",
  options: [
    { choice: "manual_input", parameters_schema: { lattice: "3×3 float — row lattice vectors, Å" } },
    {
      choice: "upload_reference",
      parameters_schema: { reference: "file_id of a same-atom-count structure" },
    },
    { choice: "bounding_box", parameters_schema: { padding_ang: "float ≥ 0 — padding, Å" } },
  ],
};

const velocities: AwaitingScenario = {
  scenario: "missing_velocities",
  path: "dynamics.velocities",
  detail: "target can carry velocities",
  options: [
    { choice: "zero_init" },
    {
      choice: "maxwell_boltzmann",
      parameters_schema: {
        temperature_K: "float > 0 — sampling temperature",
        seed: "integer — recorded for reproducibility",
      },
    },
  ],
};

function renderCard(scenario: AwaitingScenario, extra: Record<string, unknown> = {}) {
  const onChange = vi.fn();
  render(<DecisionCard scenario={scenario} onChange={onChange} {...extra} />);
  return { onChange };
}

describe("DecisionCard", () => {
  it("names the scenario in plain language with its machine code beside it", () => {
    renderCard(lattice);
    expect(screen.getByText("No simulation cell")).toBeInTheDocument();
    expect(screen.getByText("missing_lattice")).toBeInTheDocument();
  });

  it("offers exactly the options the engine computed, and never invents one", () => {
    renderCard(lattice);
    for (const option of lattice.options) {
      expect(screen.getByRole("radio", { name: new RegExp(option.choice) })).toBeInTheDocument();
    }
    // POSCAR never offers a non-periodic cell — the card must not add it.
    expect(screen.queryByRole("radio", { name: /non_periodic/ })).not.toBeInTheDocument();
  });

  it("preselects NO option — every radio starts unchecked", () => {
    renderCard(lattice);
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).not.toBeChecked();
    }
  });

  it("reveals a choice's parameter widget only once it is selected", () => {
    renderCard(lattice);
    expect(screen.queryByLabelText(/padding_ang/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /bounding_box/ }));
    expect(screen.getByLabelText(/padding_ang/)).toBeInTheDocument();
  });

  it("emits the {choice, parameters} decision as the user fills a parameter", () => {
    const { onChange } = renderCard(lattice);
    fireEvent.click(screen.getByRole("radio", { name: /bounding_box/ }));
    fireEvent.change(screen.getByLabelText(/padding_ang/), { target: { value: "5" } });
    expect(onChange).toHaveBeenLastCalledWith({
      choice: "bounding_box",
      parameters: { padding_ang: 5 },
    });
  });

  it("renders a 3×3 grid for a lattice choice", () => {
    renderCard(lattice);
    fireEvent.click(screen.getByRole("radio", { name: /manual_input/ }));
    // Nine cells for the row lattice vectors.
    expect(screen.getAllByTestId("lattice-cell")).toHaveLength(9);
  });

  it("shows the Maxwell–Boltzmann seed as a visible, editable field (R11)", () => {
    const { onChange } = renderCard(velocities);
    fireEvent.click(screen.getByRole("radio", { name: /maxwell_boltzmann/ }));
    const seed = screen.getByLabelText(/seed/);
    expect(seed).toBeInTheDocument();
    fireEvent.change(seed, { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText(/temperature_K/), { target: { value: "300" } });
    expect(onChange).toHaveBeenLastCalledWith({
      choice: "maxwell_boltzmann",
      parameters: { temperature_K: 300, seed: 7 },
    });
  });

  it("renders the exact Assumption preview passed for this scenario, verbatim", () => {
    const sentence =
      "Generated a bounding-box cell with 5.0 Å padding around the atoms — not present in the source.";
    render(
      <DecisionCard
        scenario={lattice}
        decision={{ choice: "bounding_box", parameters: { padding_ang: 5 } }}
        preview={sentence}
        onChange={vi.fn()}
      />,
    );
    const preview = screen.getByTestId("assumption-preview");
    expect(within(preview).getByText(sentence)).toBeInTheDocument();
  });

  it("shows no Assumption preview until one is provided", () => {
    renderCard(lattice, { decision: { choice: "bounding_box", parameters: {} } });
    expect(screen.queryByTestId("assumption-preview")).not.toBeInTheDocument();
  });
});
