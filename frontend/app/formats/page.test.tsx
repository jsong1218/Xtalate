import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FormatsPage from "./page";

/**
 * The `/formats` placeholder is honest, not broken (slice M28-S1): the landing link resolves to a
 * real page that says the Capability Matrix browser is a v0.7 feature and points at where the same
 * information is already available — never a dead link, never a silent stub.
 */
describe("FormatsPage (M28-S1 honest placeholder)", () => {
  it("states the browser is coming in v0.7 and offers the working path today", () => {
    render(<FormatsPage />);
    expect(screen.getByText(/v0\.7/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /convert a file/i })).toHaveAttribute("href", "/convert");
  });
});
