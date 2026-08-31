import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SourceRail } from "./SourceRail";
import type { DiscoveryReport } from "@/lib/report/types";

/**
 * The pinned source rail (UI redesign S2, D244; D-R2): on every workspace tab it keeps the file's
 * facts in view — filename, format + confidence, the counts — and its primary CTA is the guided
 * spine's next step (the Convert tab). The facts come from the same inspection the Inspect tab
 * renders; the rail never makes a second wire call.
 */
const report: DiscoveryReport = {
  file: { filename: "relax.traj", size_bytes: 2048, sha256: "ab".repeat(32) },
  format: { format_id: "ase-trajectory", format_name: "ASE Trajectory", confidence: 0.92 },
  structure: { frame_count: 3, atom_count: 64, species: ["Si", "O"] },
  fields: [],
  extras: [],
  issues: [],
  schema_version: "1.0.0",
};

const { useInspection } = vi.hoisted(() => ({ useInspection: vi.fn() }));
vi.mock("@/lib/api/useInspection", () => ({ useInspection }));

describe("SourceRail", () => {
  beforeEach(() => {
    useInspection.mockReturnValue({ status: "ready", report });
  });

  it("pins the source facts: filename, format + confidence, and the counts", () => {
    render(<SourceRail fileId="file-1" />);
    expect(screen.getByText("relax.traj")).toBeInTheDocument();
    expect(screen.getByText(/ASE Trajectory/)).toBeInTheDocument();
    expect(screen.getByText("(92% confidence)")).toBeInTheDocument();
    // The counts render as mono values (the S1 DataValue role).
    expect(screen.getByText("3").className).toContain("font-mono");
    expect(screen.getByText("64").className).toContain("font-mono");
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("points the guided-spine CTA at the Convert tab", () => {
    render(<SourceRail fileId="file-1" />);
    const cta = screen.getByRole("link", { name: "Convert →" });
    expect(cta).toHaveAttribute("href", "/f/file-1/convert");
    expect(cta.className).toContain("bg-accent"); // the primary button treatment
  });

  it("renders a loading state while inspection is pending", () => {
    useInspection.mockReturnValue({ status: "loading" });
    render(<SourceRail fileId="file-1" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading source…");
  });
});
