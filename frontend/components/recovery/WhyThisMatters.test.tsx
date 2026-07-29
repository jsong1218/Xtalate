import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WhyThisMatters } from "./WhyThisMatters";
import { whyForScenario } from "@/lib/recovery/why";

/**
 * "Why does this matter?" progressive disclosure (MASTER_SPEC Part 7 §3.1, deliverable 6; slice
 * M31-S3). A non-expert can act on the three plain options without opening it; opening it reveals
 * the scientific stakes — what the missing thing is, and which choices are safe for which purposes.
 * The copy lives in {@link whyForScenario} and is lint-covered; this proves the disclosure renders
 * it honestly and never as a wall of prose the reader must read to proceed.
 */
describe("WhyThisMatters", () => {
  it("offers the stakes behind a collapsed disclosure, not up front", () => {
    render(<WhyThisMatters scenario="frame_selection" />);
    const disclosure = screen.getByTestId("why-this-matters") as HTMLDetailsElement;
    // A <details> starts closed: the prompt is visible, the scientific stakes are one click away.
    expect(disclosure.open).toBe(false);
    expect(screen.getByText(/why does this matter\?/i)).toBeInTheDocument();
  });

  it("reveals the engine scenario's scientific stakes when expanded", () => {
    const why = whyForScenario("frame_selection")!;
    render(<WhyThisMatters scenario="frame_selection" />);
    const disclosure = screen.getByTestId("why-this-matters") as HTMLDetailsElement;
    fireEvent.click(within(disclosure).getByText(why.question));
    // The copy shown is exactly the constant's — the component never paraphrases it.
    for (const paragraph of why.stakes) {
      expect(within(disclosure).getByText(paragraph)).toBeInTheDocument();
    }
  });

  it("renders nothing for a scenario it has no copy for (a future plugin's)", () => {
    const { container } = render(<WhyThisMatters scenario="some_plugin_scenario" />);
    expect(container).toBeEmptyDOMElement();
  });
});
