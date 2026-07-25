import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobPhase, elapsedSeconds, formatElapsed, phaseLabel } from "./JobPhase";
import type { JobEnvelope } from "@/lib/api/queries";
import awaitingJob from "./__fixtures__/job.awaiting_recovery.json";

/**
 * The phase indicator (MASTER_SPEC Part 7 §2.4; slice M29-S1).
 *
 * The base envelope is real service output (`GET /v1/jobs/{id}` for a paused convert), so the field
 * names, timestamp format, and `progress` shape are the engine's own. A *running* job cannot be
 * captured from the inline queue — it completes within the request — so the two running cases below
 * take that real envelope and override only `state` and `progress`, which is exactly the pair the
 * worker restamps as it moves through the pipeline.
 *
 * The load-bearing assertion is the negative one: **with no frame counters there is no progress
 * bar.** A UI that invents one is inventing a number the engine never produced.
 */

const base = awaitingJob as unknown as JobEnvelope;

const running = (progress: JobEnvelope["progress"]): JobEnvelope => ({
  ...base,
  state: "running",
  progress,
});

// The fixture's own `started_at`, plus 75 seconds — a deterministic stand-in for the wall clock.
const startedAt = Date.parse(`${base.started_at}Z`);

describe("phaseLabel", () => {
  it("gives a plain-language name for each phase the worker stamps", () => {
    expect(phaseLabel("parsing")).toBe("Reading the source file");
    expect(phaseLabel("converting")).toBe("Writing the target format");
  });

  it("shows an unknown phase code verbatim rather than hiding or guessing it", () => {
    expect(phaseLabel("resampling")).toBe("resampling");
  });

  it("falls back to a neutral word when the service reported no phase at all", () => {
    expect(phaseLabel(null)).toBe("Working");
    expect(phaseLabel(undefined)).toBe("Working");
  });
});

describe("elapsed time", () => {
  it("reads the service's naive-UTC timestamps as UTC, not local time", () => {
    // A naive timestamp parsed as local time would be off by the runner's offset — hours, not
    // seconds — so this pins the anchoring rather than the arithmetic.
    expect(elapsedSeconds(base.started_at, startedAt + 30_000)).toBe(30);
  });

  it("returns null when there is no timestamp to measure from", () => {
    expect(elapsedSeconds(null, Date.now())).toBeNull();
  });

  it("formats seconds as m:ss and h:mm:ss", () => {
    expect(formatElapsed(9)).toBe("0:09");
    expect(formatElapsed(75)).toBe("1:15");
    expect(formatElapsed(3675)).toBe("1:01:15");
  });
});

describe("JobPhase rendering", () => {
  it("shows the plain phase, its machine code, and the elapsed time", () => {
    render(<JobPhase envelope={running({ phase: "parsing" })} now={startedAt + 75_000} />);
    expect(screen.getByText("Reading the source file")).toBeInTheDocument();
    expect(screen.getByText("parsing")).toBeInTheDocument();
    expect(screen.getByText("1:15 elapsed")).toBeInTheDocument();
  });

  it("renders NO progress bar when the engine reported no frame counters", () => {
    render(<JobPhase envelope={running({ phase: "converting" })} now={startedAt + 1_000} />);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("frame-progress")).not.toBeInTheDocument();
    // …and says so, rather than leaving a reader to wonder whether it stalled.
    expect(screen.getByText(/no progress bar to show/i)).toBeInTheDocument();
  });

  it("renders a bar only from real counts, labelled with those counts", () => {
    render(
      <JobPhase
        envelope={running({ phase: "converting", frames_processed: 12, frames_total: 40 })}
        now={startedAt + 1_000}
      />,
    );
    expect(screen.getByText("Frame 12 of 40")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Frames processed" });
    expect(bar).toHaveAttribute("aria-valuenow", "12");
    expect(bar).toHaveAttribute("aria-valuemax", "40");
  });

  it("does not divide by a zero frame total", () => {
    render(
      <JobPhase
        envelope={running({ phase: "converting", frames_processed: 0, frames_total: 0 })}
        now={startedAt + 1_000}
      />,
    );
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});
