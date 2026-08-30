/**
 * TrajectoryScrubber tests (v1.6 M61-S1, D236): the control is a **frame-number** scrubber —
 * the range bounds and the readout are absolute report indices, never a time label — with a
 * play/pause button carrying `aria-pressed`.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TrajectoryScrubber } from "./TrajectoryScrubber";

describe("TrajectoryScrubber", () => {
  it("shows a frame-number readout ('frame N / M'), never a time label", () => {
    render(
      <TrajectoryScrubber frameCount={6} frameIndexBase={0} frame={2} onScrub={vi.fn()} />,
    );
    // The readout names the absolute report index and the object's total — a frame number.
    expect(screen.getByRole("status")).toHaveTextContent("2 / 6");
    const range = screen.getByRole("slider", { name: /Trajectory frame/ });
    expect(range).toHaveAttribute("min", "0");
    expect(range).toHaveAttribute("max", "5");
    expect(screen.queryByText(/(ps|fs|step|time|picosecond)/i)).toBeNull();
  });

  it("exposes the keyboard contract: a native range with an accessible name and frame bounds (M63-S2)", () => {
    // The scrubber's keyboard bar (D241): the control is a native `range` input — role slider,
    // an accessible name, and integer frame bounds/step — so a keyboard user can arrow through
    // the trajectory exactly as a mouse user scrubs (the real-browser behavior is proven by the
    // keyboard e2e journey; this pins the ARIA contract jsdom can assert).
    render(
      <TrajectoryScrubber frameCount={6} frameIndexBase={100} frame={103} onScrub={vi.fn()} />,
    );
    const range = screen.getByRole("slider", { name: "Trajectory frame" });
    expect(range.tagName).toBe("INPUT");
    expect(range).toHaveAttribute("type", "range");
    expect(range).toHaveAttribute("min", "100"); // the absolute base — report indices, not local
    expect(range).toHaveAttribute("max", "105");
    expect(range).toHaveAttribute("step", "1");
    expect(range).toHaveAttribute("value", "103");
  });

  it("labels the exported-frame marker with the report's own frame number (M63-S2)", () => {
    render(
      <TrajectoryScrubber
        frameCount={6}
        frameIndexBase={0}
        frame={2}
        onScrub={vi.fn()}
        markerFrame={3}
      />,
    );
    // The marker is labeled text — the report's own integer, rendered verbatim (D237) — not a
    // bare tick; the track tick itself is decorative (aria-hidden) so it never doubles the name.
    expect(screen.getByTestId("exported-frame-marker")).toHaveTextContent("Exported frame 3");
    const tick = screen.getByTestId("exported-frame-track-marker");
    expect(tick).toHaveAttribute("aria-hidden", "true");
  });

  it("reports the scrubbed absolute index; the readout is absolute even with a non-zero base", () => {
    const onScrub = vi.fn();
    render(
      <TrajectoryScrubber frameCount={6} frameIndexBase={100} frame={104} onScrub={onScrub} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("104 / 6");
    fireEvent.change(screen.getByRole("slider", { name: /Trajectory frame/ }), {
      target: { value: "103" },
    });
    expect(onScrub).toHaveBeenCalledWith(103);
  });

  it("play/pause is a button carrying aria-pressed, and playback stops at the last frame", async () => {
    const onScrub = vi.fn();
    const utils = render(
      <TrajectoryScrubber frameCount={6} frameIndexBase={0} frame={0} onScrub={onScrub} />,
    );
    const play = screen.getByRole("button", { name: "Play" });
    expect(play).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(play);
    expect(screen.getByRole("button", { name: "Pause" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Playback advances until the last frame, then stops rather than wrapping.
    await waitFor(() => expect(onScrub).toHaveBeenCalled(), { timeout: 2000 });
    utils.rerender(
      <TrajectoryScrubber frameCount={6} frameIndexBase={0} frame={5} onScrub={onScrub} />,
    );
    await waitFor(() => screen.getByRole("button", { name: "Play" }));
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("shows an honest loading affordance while a window fetch is in flight", () => {
    render(
      <TrajectoryScrubber
        frameCount={6}
        frameIndexBase={0}
        frame={0}
        onScrub={vi.fn()}
        isLoading
      />,
    );
    expect(screen.getByTestId("trajectory-loading")).toHaveTextContent("loading…");
  });

  it("surfaces the honest large-trajectory affordance, never a hidden stall (M61-S3)", () => {
    const { rerender } = render(
      <TrajectoryScrubber
        frameCount={6}
        frameIndexBase={0}
        frame={0}
        onScrub={vi.fn()}
        isLarge
      />,
    );
    expect(screen.getByTestId("trajectory-large")).toHaveTextContent("scrubbing may be slower");
    rerender(
      <TrajectoryScrubber frameCount={6} frameIndexBase={0} frame={0} onScrub={vi.fn()} />,
    );
    expect(screen.queryByTestId("trajectory-large")).toBeNull();
  });

  it("honours the playback step interval (a fast dev-run rate, the production default otherwise)", async () => {
    const onScrub = vi.fn();
    render(
      <TrajectoryScrubber
        frameCount={6}
        frameIndexBase={0}
        frame={0}
        onScrub={onScrub}
        playIntervalMs={20}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    // A 20 ms interval advances far sooner than the fixed 600 ms default would.
    await waitFor(() => expect(onScrub).toHaveBeenCalled(), { timeout: 1000 });
  });
});