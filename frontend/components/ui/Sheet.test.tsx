import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Sheet } from "./Sheet";

describe("Sheet", () => {
  it("renders nothing while closed", () => {
    render(
      <Sheet open={false} onClose={() => {}} title="Shortcuts">
        <p>body</p>
      </Sheet>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is a modal dialog named by its title, with a labelled close button, and takes focus", () => {
    render(
      <Sheet open onClose={() => {}} title="Shortcuts">
        <p>body</p>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog", { name: "Shortcuts" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByRole("button", { name: "Close Shortcuts" })).toBeTruthy();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("closes on Escape and on the close button", async () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose} title="Shortcuts">
        <p>body</p>
      </Sheet>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Close Shortcuts" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("returns focus to the opener when it closes", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            open
          </button>
          <Sheet open={open} onClose={() => setOpen(false)} title="Shortcuts">
            <p>body</p>
          </Sheet>
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "open" });
    await userEvent.click(opener);
    expect(screen.getByRole("dialog")).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});
