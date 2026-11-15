import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusCell, Table, Td, Th } from "./Table";

describe("Table primitives", () => {
  it("renders a captioned table with column headers and right-aligned numeric cells", () => {
    render(
      <Table caption="Pre-flight">
        <thead>
          <tr>
            <Th>Field</Th>
            <Th numeric>Residual</Th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <Td>atoms.positions</Td>
            <Td numeric>2.1e-15</Td>
          </tr>
        </tbody>
      </Table>,
    );
    expect(screen.getByRole("table", { name: "Pre-flight" })).toBeTruthy();
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((h) => h.getAttribute("scope"))).toEqual(["col", "col"]);
    expect(headers[1].className).toContain("text-right");
    const numeric = screen.getByRole("cell", { name: "2.1e-15" });
    expect(numeric.className).toContain("text-right");
    expect(numeric.className).toContain("tabular-nums");
  });

  it("StatusCell colours by tone and keeps the dot out of the accessibility tree", () => {
    render(
      <table>
        <tbody>
          <tr>
            <StatusCell tone="removed">dropped</StatusCell>
          </tr>
        </tbody>
      </table>,
    );
    const cell = screen.getByRole("cell", { name: "dropped" });
    expect(cell.className).toContain("text-cb-removed");
    const dot = cell.querySelector("[aria-hidden='true']")!;
    expect(dot.className).toContain("bg-cb-removed");
  });
});
