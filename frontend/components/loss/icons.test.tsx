import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LOSS_GLYPHS, LossIcon, LossTag, type LossKind } from "./icons";

const ALL_KINDS = Object.keys(LOSS_GLYPHS) as LossKind[];

describe("loss icon vocabulary (Part 7 §4)", () => {
  it("covers all eight §4 meanings", () => {
    expect(ALL_KINDS).toHaveLength(8);
  });

  it.each(ALL_KINDS)("LossIcon(%s) exposes an accessible label — never color-only", (kind) => {
    render(<LossIcon kind={kind} />);
    // The invariant that makes the palette accessible: every icon carries text meaning.
    expect(screen.getByRole("img", { name: LOSS_GLYPHS[kind].label })).toBeInTheDocument();
  });

  it.each(ALL_KINDS)("LossTag(%s) renders a visible text label beside the glyph", (kind) => {
    render(<LossTag kind={kind} />);
    expect(screen.getByText(LOSS_GLYPHS[kind].label)).toBeVisible();
  });

  it("honors an overridden label while keeping the kind's accessible name", () => {
    render(<LossTag kind="removed">Forces dropped</LossTag>);
    expect(screen.getByText("Forces dropped")).toBeVisible();
    expect(screen.getByRole("img", { name: "Removed" })).toBeInTheDocument();
  });
});
