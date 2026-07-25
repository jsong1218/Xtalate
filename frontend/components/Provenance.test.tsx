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
 * The captured fixtures show that today the embedded report carries `source.sha256: null` on the
 * HTTP path — the upload row stores the digest, but the convert worker never passes it to
 * `ConversionEngine.convert(source_sha256=…)`, so the service records a conversion without saying
 * which bytes it converted. That is a service-side gap, tracked separately; the UI's job is to make
 * it *visible* rather than to paper over it, which is what the "not recorded" assertion pins down.
 * When the worker starts supplying it, the digest-rendering test below is what proves it arrives.
 */

const happy = record as unknown as ConversionRecord;
const refused = refusedRecord as unknown as ConversionRecord;

describe("Provenance", () => {
  it("says the source digest is not recorded when the service did not send one", () => {
    // Both the projection and the embedded report are hash-less on the HTTP path today.
    expect(happy.source).not.toHaveProperty("sha256");
    expect(happy.conversion_report.source.sha256).toBeNull();

    render(<Provenance record={happy} />);
    const strip = screen.getByTestId("provenance");
    // An unknown digest must never read as "no digest was needed", and must never be blank.
    expect(within(strip).getByText(/source sha256/i)).toBeInTheDocument();
    expect(within(strip).getAllByText(/not recorded/i).length).toBeGreaterThan(0);
  });

  it("cites the digest from the embedded report once one is present, abbreviated but complete", () => {
    const sha256 = "4f2a91c0d3be77105ec49b2f6d0aa31c8e5b7742f9c0a1d3e6b8074f2c9a1b3d";
    const withHash = {
      ...happy,
      conversion_report: {
        ...happy.conversion_report,
        source: { ...happy.conversion_report.source, sha256 },
      },
    };

    render(<Provenance record={withHash} />);
    const strip = screen.getByTestId("provenance");
    expect(within(strip).getByText(`${shortHash(sha256)}…`)).toBeInTheDocument();
    // The full digest stays available to copy, rather than being truncated away entirely.
    expect(within(strip).getByTitle(sha256)).toBeInTheDocument();
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
