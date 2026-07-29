import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RecoveryStep } from "./RecoveryStep";
import type { JobEnvelope } from "@/lib/api/queries";
import type { AwaitingRecoveryBlock } from "@/lib/report/types";
import awaitingJob from "@/components/__fixtures__/job.awaiting_recovery.json";

/**
 * The recovery **step** (M31-S2, MASTER_SPEC Part 7 §3.1) — the wrapper that turns a paused job into a
 * full-width scientific decision surface: the framing line, the visible deadline stated as a refusal,
 * the pre-flight draft as §4 summary chips, the {@link RecoveryWizard} it hosts, and the first-class
 * decline. The fixture is the README's own paused conversion (two-frame, lattice-less XYZ → POSCAR),
 * so both `frame_selection` and `missing_lattice` are open — asserted against engine output.
 */

const envelope = awaitingJob as unknown as JobEnvelope;
const block = envelope.awaiting_recovery as unknown as AwaitingRecoveryBlock;
const oneScenarioBlock: AwaitingRecoveryBlock = {
  ...block,
  unresolved_scenarios: [block.unresolved_scenarios[0]],
};

function okSubmit() {
  return vi.fn(async () => ({ ok: true as const, envelope }));
}

function renderStep(props: Partial<React.ComponentProps<typeof RecoveryStep>> = {}) {
  return render(
    <RecoveryStep
      block={block}
      jobId={envelope.job_id}
      expiresAt={envelope.expires_at}
      onResumed={vi.fn()}
      onDecline={vi.fn()}
      submit={okSubmit()}
      {...props}
    />,
  );
}

describe("RecoveryStep", () => {
  it("frames how many decisions the conversion still owes, pluralised", () => {
    renderStep();
    expect(
      screen.getByRole("heading", { name: /needs 2 decisions before it can proceed/i }),
    ).toBeInTheDocument();
  });

  it("frames a single decision in the singular", () => {
    renderStep({ block: oneScenarioBlock });
    expect(
      screen.getByRole("heading", { name: /needs 1 decision before it can proceed/i }),
    ).toBeInTheDocument();
  });

  it("renders the pre-flight draft as summary chips, in view before any decision", () => {
    renderStep();
    const summary = screen.getByLabelText("Conversion summary");
    // Straight off the draft report arrays (preserved 2, removed 1) — the client never recomputes loss.
    expect(within(summary).getByText("2 fields preserved")).toBeInTheDocument();
    expect(within(summary).getByText("1 field removed")).toBeInTheDocument();
  });

  it("states the deadline as a refusal for want of a decision, never a default", () => {
    renderStep();
    const deadline = screen.getByTestId("recovery-deadline");
    expect(deadline).toHaveTextContent(envelope.expires_at!);
    expect(deadline).toHaveTextContent(/refused/i);
    expect(deadline).toHaveTextContent(/no default is applied/i);
    expect(deadline).toHaveTextContent(/no value is invented/i);
    expect(deadline.textContent).not.toMatch(/default (will|would) be (used|applied)/i);
  });

  it("still states the refusal rule when the service reported no deadline", () => {
    renderStep({ expiresAt: null });
    expect(screen.getByTestId("recovery-deadline")).toHaveTextContent(/refused/i);
  });

  it("hosts one decision card per unresolved scenario", () => {
    renderStep();
    expect(screen.getAllByTestId("decision-card")).toHaveLength(
      block.unresolved_scenarios.length,
    );
  });

  it("offers a first-class decline that never traps the user", () => {
    const onDecline = vi.fn();
    renderStep({ onDecline });
    fireEvent.click(screen.getByRole("button", { name: /cancel conversion/i }));
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  it("surfaces a decline error through the shared error envelope, code verbatim", () => {
    renderStep({
      declineError: {
        error: {
          code: "JOB_ALREADY_TERMINAL",
          message: "This job has already finished.",
          details: {},
          request_id: "req_1",
          documentation_url: "",
        },
      },
    });
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("JOB_ALREADY_TERMINAL")).toBeInTheDocument();
  });

  it("resumes through the hosted wizard — a completed submit calls onResumed with the envelope", async () => {
    const onResumed = vi.fn();
    renderStep({ onResumed, submit: okSubmit() });
    fireEvent.click(screen.getByRole("radio", { name: /^last$/ }));
    fireEvent.click(screen.getByRole("radio", { name: /bounding_box/ }));
    fireEvent.change(screen.getByLabelText(/padding_ang/), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onResumed).toHaveBeenCalledWith(envelope));
  });
});
