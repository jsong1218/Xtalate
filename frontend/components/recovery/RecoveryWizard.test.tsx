import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RecoveryWizard } from "./RecoveryWizard";
import type { JobEnvelope } from "@/lib/api/queries";
import type { AwaitingRecoveryBlock } from "@/lib/report/types";
import awaitingJob from "@/components/__fixtures__/job.awaiting_recovery.json";

/**
 * The Recovery Workflow wizard (M31-S1, Part 7 §3). The wizard turns a paused job's
 * `awaiting_recovery` block into a validated `POST …/recovery` body, and it carries the deliverable-9
 * proofs: every scenario renders, in engine dependency order; nothing is preselected; the submission
 * is exactly the body the engine validated; an `INVALID_RECOVERY_CHOICE` response renders honestly.
 *
 * The fixture is the README's own paused conversion — a two-frame, lattice-less XYZ → POSCAR, so both
 * `frame_selection` and `missing_lattice` are open — asserted against engine output, not a mock shape.
 */

const envelope = awaitingJob as unknown as JobEnvelope;
const block = envelope.awaiting_recovery as unknown as AwaitingRecoveryBlock;

/** The same block with its scenarios reversed, to prove the wizard *orders* rather than passes through. */
const reversedBlock: AwaitingRecoveryBlock = {
  ...block,
  unresolved_scenarios: [...block.unresolved_scenarios].reverse(),
};

function okSubmit() {
  return vi.fn(async () => ({ ok: true as const, envelope }));
}
function okPreview(descriptions: Record<string, string>) {
  return vi.fn(async (_jobId: string, choices: Record<string, { choice: string }>) => ({
    ok: true as const,
    preview: {
      previews: Object.entries(choices).map(([scenario, decision]) => ({
        scenario,
        choice: decision.choice,
        parameters: {},
        description: descriptions[scenario] ?? "",
      })),
      unresolved: [],
    },
  }));
}

function fillFlagship() {
  fireEvent.click(screen.getByRole("radio", { name: /^last$/ }));
  fireEvent.click(screen.getByRole("radio", { name: /bounding_box/ }));
  fireEvent.change(screen.getByLabelText(/padding_ang/), { target: { value: "5" } });
}

describe("RecoveryWizard", () => {
  it("renders one decision card per unresolved scenario", () => {
    render(<RecoveryWizard block={block} jobId={envelope.job_id} submit={okSubmit()} />);
    expect(screen.getAllByTestId("decision-card")).toHaveLength(
      block.unresolved_scenarios.length,
    );
  });

  it("orders the cards in engine dependency order — frame selection before lattice", () => {
    render(<RecoveryWizard block={reversedBlock} jobId={envelope.job_id} submit={okSubmit()} />);
    const codes = screen.getAllByTestId("decision-card").map(
      (card) => within(card).getByText(/^(frame_selection|missing_lattice)$/).textContent,
    );
    expect(codes).toEqual(["frame_selection", "missing_lattice"]);
  });

  it("preselects nothing — every radio starts unchecked", () => {
    render(<RecoveryWizard block={block} jobId={envelope.job_id} submit={okSubmit()} />);
    for (const radio of screen.getAllByRole("radio")) expect(radio).not.toBeChecked();
  });

  it("disables Confirm until every decision is complete", () => {
    render(<RecoveryWizard block={block} jobId={envelope.job_id} submit={okSubmit()} />);
    const confirm = screen.getByRole("button", { name: /confirm/i });
    expect(confirm).toBeDisabled();
    fillFlagship();
    expect(confirm).toBeEnabled();
  });

  it("submits exactly the {scenario:{choice,parameters}} body the engine validates", async () => {
    const submit = okSubmit();
    const onResumed = vi.fn();
    render(
      <RecoveryWizard
        block={block}
        jobId={envelope.job_id}
        submit={submit}
        onResumed={onResumed}
      />,
    );
    fillFlagship();
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit).toHaveBeenCalledWith(envelope.job_id, {
      frame_selection: { choice: "last", parameters: {} },
      missing_lattice: { choice: "bounding_box", parameters: { padding_ang: 5 } },
    });
    await waitFor(() => expect(onResumed).toHaveBeenCalledWith(envelope));
  });

  it("previews the exact Assumption sentences once the decisions are complete", async () => {
    const preview = okPreview({
      frame_selection: "Frame 1 of 2 selected for the single-structure target.",
      missing_lattice: "Generated a bounding-box cell with 5.0 Å padding around the atoms.",
    });
    render(
      <RecoveryWizard
        block={block}
        jobId={envelope.job_id}
        submit={okSubmit()}
        preview={preview}
      />,
    );
    fillFlagship();

    await screen.findByText("Generated a bounding-box cell with 5.0 Å padding around the atoms.");
    expect(
      screen.getByText("Frame 1 of 2 selected for the single-structure target."),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("assumption-preview")).toHaveLength(2);
  });

  it("renders an INVALID_RECOVERY_CHOICE response with its offered_choices, verbatim", async () => {
    const submit = vi.fn(async () => ({
      ok: false as const,
      error: {
        error: {
          code: "INVALID_RECOVERY_CHOICE",
          message: "'non_periodic' is not an offered choice for 'missing_lattice'.",
          details: { scenario: "missing_lattice", offered_choices: ["bounding_box"] },
          request_id: "req_1",
          documentation_url: "",
        },
      },
    }));
    render(<RecoveryWizard block={block} jobId={envelope.job_id} submit={submit} />);
    fillFlagship();
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("INVALID_RECOVERY_CHOICE")).toBeInTheDocument();
    expect(within(alert).getByText(/offered_choices/)).toBeInTheDocument();
    expect(within(alert).getByText(/bounding_box/)).toBeInTheDocument();
  });
});
