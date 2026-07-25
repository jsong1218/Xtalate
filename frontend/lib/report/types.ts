/**
 * Frontend report models — the Conversion Report schema, mirrored verbatim (MASTER_SPEC Part 4 §2).
 *
 * The `/v1` service embeds the library's pydantic report models **verbatim** in its responses
 * (Part 6 §1), but the OpenAPI schema types those embedded bodies as opaque `{ [key]: unknown }`
 * (see `lib/api/schema.d.ts`, e.g. `JobEnvelope.result`, `ConversionRecordResponse`). These
 * interfaces re-declare the exact same shapes on the client so the report panels have real types —
 * they are the *one* place the report vocabulary is spelled in TypeScript, and every field name,
 * literal, and nullability matches `src/xtalate/conversion/report.py`. If the Python model changes,
 * this file is what changes with it; nothing else in the UI re-derives report shape.
 *
 * These are presentation types only. The client never *computes* a report — it renders what the
 * engine produced (Part 7 §2: the faithful presentation layer). The Validation and Discovery report
 * shapes land beside these in M27-S2 / M28 as the panels that consume them arrive.
 */

/** A canonical field the target kept — Part 4 §2 `PreservedEntry`. */
export interface PreservedEntry {
  /** Canonical field path, e.g. "atoms.positions" (Part 2 §3). */
  path: string;
  /** e.g. "1 frame × 64 atoms", "converted to fractional (Direct)". */
  detail: string | null;
}

/** A canonical field present in the source but absent from the output — Part 4 §2 `RemovedEntry`. */
export interface RemovedEntry {
  path: string;
  /** REQUIRED, rendered **verbatim** — never UI-paraphrased (Part 7 §2.3). */
  reason: string;
  /** e.g. "10 frames × 64 atoms × 3 dropped". */
  detail: string | null;
}

/** A field fabricated by Recovery and written out — Part 4 §2 `SuppliedEntry`. */
export interface SuppliedEntry {
  path: string;
  /** The {@link Assumption.id} that authorized this value (P4). */
  from_assumption: string;
  detail: string | null;
}

/** A recorded recovery decision — Part 4 §2 `Assumption`. */
export interface Assumption {
  /** Stable per-report identifier, e.g. "A1". */
  id: string;
  /** Machine code: "missing_lattice", "frame_selection", … (Part 4 §3). */
  scenario: string;
  /** Machine code of the selected option: "bounding_box", … (Part 4 §3). */
  choice: string;
  parameters: Record<string, unknown>;
  /** Interactive choice vs pre-supplied in the API call. */
  origin: "user" | "preset";
  /** Human-readable sentence describing the decision. */
  description: string;
}

/** A non-fatal conversion note — Part 4 §2 `ReportWarning`. */
export interface ReportWarning {
  /** Stable machine code, e.g. "COORDINATE_REPRESENTATION_CHANGED". */
  code: string;
  message: string;
  source: "parse" | "capability" | "export";
}

/** Populated iff `status === "refused"` — Part 4 §4. */
export interface RefusalDetail {
  code: string;
  message: string;
  unresolved_scenarios: string[];
}

/** Source / target descriptors carried on the report (Part 4 §2). */
export interface ReportEndpoint {
  format_id: string;
  filename: string;
  /** Present on `source` only. */
  sha256?: string;
  /** Present on `source` only. */
  schema_version?: string;
  [key: string]: unknown;
}

/** The Conversion Report — Part 4 §2 `ConversionReport`, verbatim. */
export interface ConversionReport {
  report_id: string;
  stage: "preflight" | "final";
  status: "completed" | "awaiting_recovery" | "refused";
  mode: "strict" | "permissive";
  created_at: string;
  source: ReportEndpoint;
  target: ReportEndpoint;
  preserved: PreservedEntry[];
  removed: RemovedEntry[];
  supplied: SuppliedEntry[];
  assumptions: Assumption[];
  warnings: ReportWarning[];
  refusal: RefusalDetail | null;
}
