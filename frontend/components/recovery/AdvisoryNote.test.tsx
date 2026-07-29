import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AdvisoryNote } from "./AdvisoryNote";

/**
 * The advisory seam (MASTER_SPEC Part 7 §3.1, deliverable 8; slice M31-S3).
 *
 * When the v0.5 usage aggregation has data for an option, a plain-language advisory can render **on
 * the option** — never a changed default, never a preselection. Surfacing that data is a
 * pre-authorized cut to post-1.0 (a fresh instance has no aggregation), so this ships as the seam:
 * a component that renders the note when one is supplied and **nothing** when it is absent — which is
 * the only state a 1.0 instance ever reaches. The bright-line invariant is that it is advisory: a
 * note, not a control, so it can never become a default.
 */
describe("AdvisoryNote", () => {
  it("renders nothing when there is no advisory (the only 1.0 state)", () => {
    const { container } = render(<AdvisoryNote advisory={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the advisory carries no note", () => {
    const { container } = render(<AdvisoryNote advisory={{ note: "" }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("surfaces a supplied advisory as an advisory note, not a control", () => {
    render(<AdvisoryNote advisory={{ note: "Most conversions like this chose the last frame." }} />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Most conversions like this chose the last frame.");
    // Advisory means advisory: it is never a checkbox/radio that could carry a selection.
    expect(note.querySelector("input")).toBeNull();
  });
});
