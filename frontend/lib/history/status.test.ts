import { describe, expect, it } from "vitest";
import { historyStatus } from "./status";

/**
 * `historyStatus` maps a history row's two status fields onto the **existing** §4 loss vocabulary
 * (slice M33-S2) — it does not invent a second language for the table. The one rule that shapes the
 * mapping: §4's `fail` glyph covers *both* a failed validation *and* a refusal, so both land on
 * `fail` and are told apart by their label, never by a bespoke kind.
 */
describe("historyStatus (Part 7 §2.6, loss-vocabulary mapping)", () => {
  it("marks a refused conversion as a fail with a 'Refused' label", () => {
    expect(historyStatus({ conversion_status: "refused", validation_status: null })).toEqual({
      kind: "fail",
      label: "Refused",
    });
  });

  it("marks a completed conversion whose validation failed as a fail — but labeled distinctly", () => {
    expect(historyStatus({ conversion_status: "completed", validation_status: "failed" })).toEqual({
      kind: "fail",
      label: "Validation failed",
    });
  });

  it("marks passed-with-warnings as a warning, not a clean pass", () => {
    expect(
      historyStatus({ conversion_status: "completed", validation_status: "passed_with_warnings" }),
    ).toEqual({ kind: "warning", label: "Validation warnings" });
  });

  it("marks a completed, validation-passed conversion as preserved", () => {
    expect(historyStatus({ conversion_status: "completed", validation_status: "passed" })).toEqual({
      kind: "preserved",
      label: "Converted",
    });
  });

  it("still reads as converted when a completed row carries no validation status", () => {
    expect(historyStatus({ conversion_status: "completed", validation_status: null })).toEqual({
      kind: "preserved",
      label: "Converted",
    });
  });

  it("renders an unknown/absent conversion status honestly rather than guessing success", () => {
    expect(historyStatus({ conversion_status: null, validation_status: null })).toEqual({
      kind: "skipped",
      label: "Unknown",
    });
  });
});
