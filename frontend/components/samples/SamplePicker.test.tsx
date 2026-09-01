import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { SamplePicker } from "./SamplePicker";

describe("SamplePicker", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404 }) as Response));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows an alert when a sample cannot be fetched (never a dead button)", async () => {
    render(<SamplePicker onPick={vi.fn()} />);
    await userEvent.click(screen.getByTestId("sample-water"));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByTestId("sample-water")).not.toBeDisabled();
  });
});
