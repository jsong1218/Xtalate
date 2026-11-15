import { render } from "@testing-library/react";
import { Check } from "lucide-react";
import { describe, expect, it } from "vitest";
import { Icon } from "./Icon";

describe("Icon", () => {
  it("is decorative by default: aria-hidden, 16px, 1.5 stroke", () => {
    const { container } = render(<Icon icon={Check} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("width")).toBe("16");
    expect(svg.getAttribute("height")).toBe("16");
    expect(svg.getAttribute("stroke-width")).toBe("1.5");
  });

  it("becomes an accessible image when labelled", () => {
    const { getByRole } = render(<Icon icon={Check} label="Kept" size={14} />);
    const svg = getByRole("img", { name: "Kept" });
    expect(svg.getAttribute("aria-hidden")).toBeNull();
    expect(svg.getAttribute("width")).toBe("14");
  });
});
