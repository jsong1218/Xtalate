import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Select } from "./Select";

const options = [
  { value: "cif", label: "CIF" },
  { value: "poscar", label: "POSCAR" },
];

describe("Select", () => {
  it("is a native, labelled combobox that reports the chosen value", async () => {
    const onChange = vi.fn();
    render(<Select id="target" label="Target format" value="cif" onChange={onChange} options={options} />);
    const select = screen.getByRole("combobox", { name: "Target format" });
    expect(select.tagName).toBe("SELECT");
    await userEvent.selectOptions(select, "poscar");
    expect(onChange).toHaveBeenCalledWith("poscar");
  });

  it("keeps the label for screen readers when hidden visually", () => {
    render(<Select id="profile" label="Profile" hideLabel value="cif" onChange={() => {}} options={options} />);
    expect(screen.getByRole("combobox", { name: "Profile" })).toBeTruthy();
    expect(screen.getByText("Profile").className).toContain("sr-only");
  });
});
