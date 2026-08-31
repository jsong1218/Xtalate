import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button, buttonClasses } from "./Button";

/**
 * The shared primary-action primitive (pre-M36 addendum S3). The design language gives forward
 * actions one accent treatment; secondary and destructive actions recede. These tests pin the
 * contract every migrated call site relies on: the variant/size class vocabulary, safe defaults,
 * and honest prop forwarding — not a brittle full-string match.
 */
describe("Button", () => {
  it("renders its children and defaults to type=button (never a stray form submit)", () => {
    render(<Button>Convert</Button>);
    const button = screen.getByRole("button", { name: "Convert" });
    expect(button).toHaveAttribute("type", "button");
  });

  it("honours an explicit type", () => {
    render(<Button type="submit">Go</Button>);
    expect(screen.getByRole("button", { name: "Go" })).toHaveAttribute("type", "submit");
  });

  it("the primary variant is filled with the accent token", () => {
    render(<Button variant="primary">Convert</Button>);
    const button = screen.getByRole("button", { name: "Convert" });
    expect(button.className).toContain("bg-accent");
    expect(button.className).toContain("text-accent-fg");
  });

  it("primary variant fills with the accent token, never a hard-coded colour", () => {
    const cls = buttonClasses("primary");
    expect(cls).toContain("bg-accent");
    expect(cls).not.toMatch(/bg-blue-|bg-teal-|#/);
  });

  it("defaults to the primary variant", () => {
    render(<Button>Convert</Button>);
    expect(screen.getByRole("button", { name: "Convert" }).className).toContain("bg-accent");
  });

  it("the secondary variant is bordered and recedes (no accent fill)", () => {
    render(<Button variant="secondary">Cancel</Button>);
    const button = screen.getByRole("button", { name: "Cancel" });
    expect(button.className).toContain("border");
    expect(button.className).not.toContain("bg-accent");
  });

  it("the destructive variant uses the filled-fail token", () => {
    render(<Button variant="destructive">Delete</Button>);
    expect(screen.getByRole("button", { name: "Delete" }).className).toContain("bg-cb-fail-solid");
  });

  it("carries a focus-visible ring and disabled affordance in every variant", () => {
    render(<Button variant="ghost">Retry</Button>);
    const button = screen.getByRole("button", { name: "Retry" });
    expect(button.className).toContain("focus-visible:ring-2");
    expect(button.className).toContain("disabled:opacity-50");
  });

  it("forwards onClick, disabled, and arbitrary props (aria-pressed, className)", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <Button onClick={onClick} aria-pressed className="w-full">
        Choose a file
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Choose a file" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button.className).toContain("w-full");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(
      <Button onClick={onClick} disabled>
        Choose a file
      </Button>,
    );
    const disabled = screen.getByRole("button", { name: "Choose a file" });
    expect(disabled).toBeDisabled();
    fireEvent.click(disabled);
    expect(onClick).toHaveBeenCalledTimes(1); // no second call while disabled
  });
});

describe("buttonClasses", () => {
  it("returns a string a link can wear to look like a primary button", () => {
    const cls = buttonClasses("primary", "lg");
    expect(cls).toContain("bg-accent");
    expect(cls).toContain("text-accent-fg");
    expect(cls).toContain("px-5"); // lg size padding
  });

  it("distinguishes sizes", () => {
    expect(buttonClasses("primary", "sm")).toContain("px-3");
    expect(buttonClasses("primary", "md")).toContain("px-4");
    expect(buttonClasses("primary", "lg")).toContain("px-5");
  });
});
