import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sun } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { IconButton } from "./IconButton";

describe("IconButton", () => {
  it("is a labelled, non-submitting button with a decorative icon", () => {
    render(<IconButton icon={Sun} label="Use light theme" />);
    const button = screen.getByRole("button", { name: "Use light theme" });
    expect(button.getAttribute("type")).toBe("button");
    expect(button.getAttribute("title")).toBe("Use light theme");
    expect(button.querySelector("svg")!.getAttribute("aria-hidden")).toBe("true");
  });

  it("exposes a toggle state through aria-pressed when asked", async () => {
    const onClick = vi.fn();
    render(<IconButton icon={Sun} label="Use light theme" pressed={false} onClick={onClick} />);
    const button = screen.getByRole("button", { name: "Use light theme" });
    expect(button.getAttribute("aria-pressed")).toBe("false");
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("omits aria-pressed for plain action buttons", () => {
    render(<IconButton icon={Sun} label="Close" />);
    expect(screen.getByRole("button", { name: "Close" }).hasAttribute("aria-pressed")).toBe(false);
  });
});
