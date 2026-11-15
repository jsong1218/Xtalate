import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Disclosure } from "./Disclosure";

function Harness({ initial }: { initial: boolean }) {
  const [open, setOpen] = useState(initial);
  return (
    <Disclosure id="stage-2" open={open} onToggle={() => setOpen((v) => !v)} summary="2 · Contents">
      <p>4 fields present</p>
    </Disclosure>
  );
}

describe("Disclosure", () => {
  it("wires aria-expanded / aria-controls and hides the panel when closed", () => {
    render(<Harness initial={false} />);
    const button = screen.getByRole("button", { name: "2 · Contents" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(button.getAttribute("aria-controls")).toBe("stage-2-panel");
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("opens on click into a labelled region", async () => {
    render(<Harness initial={false} />);
    await userEvent.click(screen.getByRole("button", { name: "2 · Contents" }));
    const region = screen.getByRole("region", { name: "2 · Contents" });
    expect(region.id).toBe("stage-2-panel");
    expect(region).toHaveTextContent("4 fields present");
    expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe("true");
  });
});
