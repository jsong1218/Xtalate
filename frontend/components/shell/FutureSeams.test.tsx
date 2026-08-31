import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FutureSeams } from "./FutureSeams";

/**
 * The reserved empty seams of the workspace shell (UI redesign S6, D247; design spec §7, P6). The
 * seams are the anti-scope-creep guard: Analysis / File Repair / Assistant are named non-goals, so
 * each must render a clearly-labelled "coming later" seat and do nothing — no link, no hidden
 * behavior, nothing that a user could mistake for a working feature. This test pins the *inertness*:
 * File Repair is a genuinely `disabled` button (unfocusable, unactivatable), and the Assistant is a
 * plain labelled box, not a control — so neither can navigate or perform any action, today or by
 * accident later.
 */
describe("FutureSeams", () => {
  it("renders the two non-route seams with 'coming later' copy", () => {
    render(<FutureSeams />);
    expect(screen.getByTestId("future-seams")).toBeInTheDocument();
    expect(screen.getByTestId("seam-repair")).toBeInTheDocument();
    expect(screen.getByTestId("seam-assistant")).toBeInTheDocument();
    // Both seats say they are coming later; nothing suggests they work today.
    expect(screen.getAllByText("coming later")).toHaveLength(2);
    expect(screen.getByText(/reserved so later work can attach/)).toBeInTheDocument();
  });

  it("keeps File Repair inert — a disabled button, never activatable or navigable", () => {
    render(<FutureSeams />);
    const repair = screen.getByRole("button", { name: "File repair" });
    // A disabled button cannot be focused or activated, so the affordance genuinely does nothing.
    expect(repair).toBeDisabled();
    expect(repair).not.toHaveAttribute("href");
    expect(repair).not.toHaveAttribute("onClick");
  });

  it("keeps the Assistant a plain labelled seat, not a control", () => {
    render(<FutureSeams />);
    const seat = screen.getByTestId("seam-assistant");
    // It is a description of a reserved slot, not an interactive element.
    expect(seat.querySelector("a, button, [role=button], [role=link]")).toBeNull();
    expect(screen.getByText("Assistant")).toBeInTheDocument();
  });
});