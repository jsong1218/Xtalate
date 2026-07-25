import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AwaitingRecovery } from "./AwaitingRecovery";
import type { JobEnvelope } from "@/lib/api/queries";
import type { AwaitingRecoveryBlock } from "@/lib/report/types";
import awaitingJob from "./__fixtures__/job.awaiting_recovery.json";

/**
 * The `awaiting_recovery` placeholder (MASTER_SPEC Part 6 §3.2, Part 7 §2.4; slice M29-S1).
 *
 * The fixture is a real paused job: a two-frame, lattice-less XYZ asked to become a POSCAR, which
 * is the README's own worked example. POSCAR holds one structure and requires a lattice, so the
 * service pauses with **both** scenarios unresolved — `frame_selection` and `missing_lattice` —
 * each carrying the option codes pre-flight actually computed for this pair. That makes the
 * "both scenarios named" requirement assertable against engine output rather than a hand-built shape.
 *
 * The load-bearing assertion is the deadline wording: an expired pause is a **refusal**, and the
 * copy must never suggest a default gets applied.
 */

const envelope = awaitingJob as unknown as JobEnvelope;
const block = envelope.awaiting_recovery as unknown as AwaitingRecoveryBlock;

function renderPause() {
  return render(
    <AwaitingRecovery block={block} jobId={envelope.job_id} expiresAt={envelope.expires_at} />,
  );
}

describe("AwaitingRecovery", () => {
  it("names every unresolved scenario the service reported", () => {
    renderPause();
    const cards = screen.getAllByTestId("awaiting-scenario");
    // Count against the fixture array, so a dropped scenario fails loudly.
    expect(cards).toHaveLength(block.unresolved_scenarios.length);
    expect(cards).toHaveLength(2);
  });

  it("shows each scenario in plain language with its machine code beside it", () => {
    renderPause();
    // `frame_selection` / `missing_lattice` resolved through the M26 mapping table.
    expect(screen.getByText("Pick which snapshot to keep")).toBeInTheDocument();
    expect(screen.getByText("frame_selection")).toBeInTheDocument();
    expect(screen.getByText("No simulation cell")).toBeInTheDocument();
    expect(screen.getByText("missing_lattice")).toBeInTheDocument();
  });

  it("renders the engine's own detail verbatim", () => {
    renderPause();
    const details = block.unresolved_scenarios.map((s) => s.detail).filter(Boolean) as string[];
    expect(details.length).toBeGreaterThan(0);
    for (const detail of details) expect(screen.getByText(detail)).toBeInTheDocument();
  });

  it("lists exactly the choices the engine computed for this pair, and their parameters", () => {
    renderPause();
    const lattice = screen
      .getAllByTestId("awaiting-scenario")
      .find((card) => within(card).queryByText("missing_lattice"));
    expect(lattice).toBeDefined();
    const scenario = block.unresolved_scenarios.find((s) => s.scenario === "missing_lattice")!;
    for (const option of scenario.options) {
      expect(within(lattice!).getByText(option.choice)).toBeInTheDocument();
    }
    // The engine offers no `non_periodic` for a POSCAR target — the UI must not invent one.
    expect(within(lattice!).queryByText("non_periodic")).not.toBeInTheDocument();
    // A parameterised choice advertises the parameter name the Recovery Engine actually reads.
    expect(within(lattice!).getByText("padding_ang")).toBeInTheDocument();
  });

  it("states that the deadline refuses the conversion — never that a default is applied", () => {
    renderPause();
    const deadline = screen.getByTestId("recovery-deadline");
    expect(deadline).toHaveTextContent(/refused/i);
    expect(deadline).toHaveTextContent(/no default is applied/i);
    expect(deadline).toHaveTextContent(/no value is invented/i);
    expect(deadline.textContent).not.toMatch(/default (will|would) be (used|applied)/i);
  });

  it("shows the pause's own deadline when the service reported one", () => {
    renderPause();
    expect(screen.getByTestId("recovery-deadline")).toHaveTextContent(envelope.expires_at!);
  });

  it("still states the refusal rule when no deadline was reported", () => {
    render(<AwaitingRecovery block={block} jobId={envelope.job_id} expiresAt={null} />);
    expect(screen.getByTestId("recovery-deadline")).toHaveTextContent(/refused/i);
  });

  it("points at the API and CLI routes that work today, and says browser choice is next", () => {
    renderPause();
    expect(
      screen.getByText(`POST /v1/jobs/${envelope.job_id}/recovery`),
    ).toBeInTheDocument();
    expect(screen.getByText(/arrives in the next version/i)).toBeInTheDocument();
  });

  it("renders the pre-flight draft report underneath the pause", () => {
    renderPause();
    expect(screen.getByText(/what this conversion looks like so far/i)).toBeInTheDocument();
    // The draft is a real pre-flight report — its preserved rows are the engine's.
    expect(block.draft_report.stage).toBe("preflight");
    expect(block.draft_report.status).toBe("awaiting_recovery");
  });
});
