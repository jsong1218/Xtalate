import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Provenance, shortHash } from "./Provenance";
import record from "@/components/__fixtures__/conversion.record.json";
import refusedRecord from "@/components/__fixtures__/conversion.record.refused.json";
import type { ConversionRecord } from "@/lib/report/types";

/**
 * The provenance strip (MASTER_SPEC Part 2 §3.7, Part 7 §2.6; slice M29-S2).
 *
 * The point of these tests is *where each fact comes from*. The record's own `source`/`target` are
 * a reduced projection with the hashes stripped (`routers/conversions.py::_endpoint`), so the strip
 * reads the digest and schema version off the **embedded** conversion report, which keeps them.
 *
 * The fixtures are captured from the service, so the first test is an end-to-end assertion that the
 * digest survives the whole path: upload → convert → record → this strip. It was not always so —
 * the convert worker used to drop the sha256 the upload had already computed, and every served
 * report carried `source.sha256: null` (fixed under D94, which is why these fixtures were
 * regenerated). The null case is still covered below, because a *future* absence must read as an
 * unknown rather than as a blank cell that a reader could mistake for "no digest was needed".
 */

const happy = record as unknown as ConversionRecord;
const refused = refusedRecord as unknown as ConversionRecord;

describe("Provenance", () => {
  it("cites the digest from the embedded report, not the stripped projection", () => {
    // The projection genuinely has no hash — this is the shape the service sends — so a strip that
    // read `record.source.sha256` would render nothing on every real response.
    expect(happy.source).not.toHaveProperty("sha256");
    const sha256 = happy.conversion_report.source.sha256 as string;
    expect(sha256).toMatch(/^[0-9a-f]{64}$/);

    render(<Provenance record={happy} />);
    const strip = screen.getByTestId("provenance");
    expect(within(strip).getByText(`${shortHash(sha256)}…`)).toBeInTheDocument();
    // The full digest stays available to copy, rather than being truncated away entirely.
    expect(within(strip).getByTitle(sha256)).toBeInTheDocument();
  });

  it("says an absent digest is unknown rather than leaving the cell blank", () => {
    const withoutHash = {
      ...happy,
      conversion_report: {
        ...happy.conversion_report,
        source: { ...happy.conversion_report.source, sha256: null },
      },
    } as unknown as ConversionRecord;

    render(<Provenance record={withoutHash} />);
    const strip = screen.getByTestId("provenance");
    expect(within(strip).getByText(/source sha256/i)).toBeInTheDocument();
    expect(within(strip).getAllByText(/not recorded/i).length).toBeGreaterThan(0);
  });

  it("carries the citable identifiers: conversion id, both report ids, mode and profile", () => {
    render(<Provenance record={happy} />);
    const strip = screen.getByTestId("provenance");
    expect(within(strip).getByText(happy.conversion_id)).toBeInTheDocument();
    expect(within(strip).getByText(happy.conversion_report.report_id)).toBeInTheDocument();
    expect(within(strip).getByText(happy.validation_report!.report_id)).toBeInTheDocument();
    expect(within(strip).getByText(happy.conversion_report.mode)).toBeInTheDocument();
    // The profile is read off the Validation Report's self-contained record of it (Part 5 §4.2).
    expect(
      within(strip).getByText(happy.validation_report!.tolerance_profile.name as string),
    ).toBeInTheDocument();
  });

  it("says why a missing value is missing instead of rendering a blank cell", () => {
    // A refused conversion has no validation report at all — so there is no profile and no id.
    expect(refused.validation_report).toBeNull();
    render(<Provenance record={refused} />);
    const strip = screen.getByTestId("provenance");
    expect(within(strip).getByText(/no validation ran/i)).toBeInTheDocument();
    expect(within(strip).getByText(/^none$/i)).toBeInTheDocument();
  });
});
