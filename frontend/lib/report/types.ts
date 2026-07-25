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
 * engine produced (Part 7 §2: the faithful presentation layer). The Conversion Report and Validation
 * Report shapes live here (M27), and the Discovery Report beside them (M28, as its page arrives).
 * The service-owned {@link ErrorEnvelope} lives here too — the report panels and the error
 * component share one typed home for everything that crosses the `/v1` wire opaque.
 */

import type { CapabilityLevel } from "@/lib/capabilities/types";

// --- Discovery Report (MASTER_SPEC Part 3 §6.2) ------------------------------------------------
//
// Mirrors `src/xtalate/discovery/report.py` verbatim. The ✓/✗ inventory the Information Discovery
// Engine produces for a sniffed-and-parsed file: which canonical fields it contains, each annotated
// with the *read-side* capability of the **detected** format. `fields` is complete over the
// canonical scientific leaf paths — every one appears exactly once, present or absent — so "not
// shown" can never be mistaken for "not checked" (§6.3). Emitted verbatim by `/v1/inspect`.

/** One canonical field's presence in the inspected file — Part 3 §6.2 `FieldPresenceEntry`. */
export interface FieldPresenceEntry {
  /** Canonical field path, e.g. "dynamics.velocities" (Part 2 §3). */
  path: string;
  /** "present" | "absent" | "mixed" — "mixed" = present in some frames only (Part 2 §3.11). */
  status: "present" | "absent" | "mixed";
  /** Populated only when `status === "mixed"`: the frame indices where the field is present. */
  present_frames: number[] | null;
  /** Read-side capability of the **detected source** format for this path (not the target's). */
  format_capability: CapabilityLevel;
  /** e.g. "2 frames × 3 atoms, Cartesian (Å)". */
  detail: string | null;
}

/**
 * The Discovery Report — Part 3 §6.2 `DiscoveryReport`, verbatim. `file`, `format`, and `structure`
 * are format-specific dictionaries the engine assembles (typed loosely, as in Python), while
 * `fields` is the fixed-schema leaf-path inventory the page renders row by row.
 */
export interface DiscoveryReport {
  /** `{ filename, size_bytes, sha256 }`. */
  file: { filename: string; size_bytes: number; sha256: string; [key: string]: unknown };
  /** `{ format_id, format_name, confidence, overridden, ambiguous, sniff_evidence: [...] }`. */
  format: {
    format_id: string;
    format_name: string;
    confidence: number;
    overridden?: boolean;
    ambiguous?: boolean;
    sniff_evidence?: { format_id: string; confidence: number }[];
    [key: string]: unknown;
  };
  /** `{ frame_count, atom_count, species: [...] }`. */
  structure: {
    frame_count: number;
    atom_count: number;
    species: string[];
    [key: string]: unknown;
  };
  /** One entry per canonical leaf path — complete, present or absent (§6.3). */
  fields: FieldPresenceEntry[];
  /** Carried-through custom_* / simulation.extra keys. */
  extras: string[];
  /** Warnings raised while parsing the file (Part 3 §5) — same shape as {@link ParseIssue}. */
  issues: ParseIssue[];
  /** Of the Canonical Object produced. */
  schema_version: string;
}

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

/**
 * One recovery the pre-flight detected but that no supplied choice resolved — Part 4 §3, the
 * elements of a {@link RefusalDetail.unresolved_scenarios} list. The engine serializes exactly
 * these four fields of `recovery.UnresolvedScenario` into the refusal dict (`params` is dropped):
 * `path` is the canonical field a *fabricative* scenario would supply and is `null` for a
 * selective-reductive one (`frame_selection`); `options` is the honest, pair-specific list of
 * `choice` codes offered for this concrete source→target.
 */
export interface UnresolvedScenario {
  /** Machine code, e.g. "missing_lattice" — resolved to a plain label via `lib/mapping.ts`. */
  scenario: string;
  path: string | null;
  detail: string | null;
  options: string[];
}

/**
 * Populated iff `status === "refused"` — Part 4 §4. `unresolved_scenarios` is a list of
 * {@link UnresolvedScenario} **objects**, not bare strings: the `RECOVERY_REQUIRED` refusal carries
 * each unresolved recovery's path/detail/options, while `UNACKNOWLEDGED_LOSS` carries `[]`. (Mirrors
 * the untyped `refusal: dict` the engine assembles in `conversion/engine.py`.)
 */
export interface RefusalDetail {
  /** Stable machine code: "RECOVERY_REQUIRED" | "UNACKNOWLEDGED_LOSS" (Part 4 §4). */
  code: string;
  message: string;
  unresolved_scenarios: UnresolvedScenario[];
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

// --- Validation Report (MASTER_SPEC Part 5 §3) -------------------------------------------------
//
// Mirrors `src/xtalate/validation/report.py` verbatim. The Validation Report is the post-conversion
// re-parse-and-diff: one `CheckResult` per executed *or skipped* check from the §2 catalog. A
// skipped check is reported, never omitted (an absent result would leave a reader guessing whether
// fidelity was verified or forgotten) — so the panel renders `skipped` rows, it does not filter
// them. The aggregate `status` is the worst individual check outcome.

/** A single fidelity check's outcome — Part 5 §3 `CheckResult`. */
export interface CheckResult {
  /** Stable machine code from the Part 5 §2 catalog, e.g. "positions_rmsd". */
  check_id: string;
  status: "pass" | "warn" | "fail" | "skipped";
  /** Canonical field paths this check examined. */
  paths: string[];
  /** Check-specific measurements, e.g. `{ rmsd_ang: 3.2e-13, frames_compared: 1 }`. */
  measured: Record<string, unknown>;
  /** Effective thresholds used (§4); `null` for exact/discrete checks. */
  tolerance_applied: Record<string, unknown> | null;
  /** Human-readable outcome — specific and quantitative; rendered verbatim. */
  message: string;
  /** Populated iff `status === "skipped"` — shown, never hidden (Part 5 §3). */
  skip_reason: string | null;
}

/**
 * A parse issue raised while re-parsing the output — Part 3 §5 `ParseIssue`. An output that parses
 * only with warnings is itself a finding, so these surface in the Validation panel.
 */
export interface ParseIssue {
  severity: "warning" | "error";
  code: string;
  message: string;
  location: string | null;
  recovery_hint: string | null;
}

/** The Validation Report — Part 5 §3 `ValidationReport`, verbatim. */
export interface ValidationReport {
  report_id: string;
  /** Links to the {@link ConversionReport} this validates (Part 4 §2). */
  conversion_report_id: string;
  created_at: string;
  /** Worst `CheckResult` determines it (Part 5 §3). */
  status: "passed" | "passed_with_warnings" | "failed";
  checks: CheckResult[];
  /** The full profile in force (§4): name + every effective threshold; self-contained. */
  tolerance_profile: Record<string, unknown>;
  /** Warnings raised while re-parsing the output (Part 3 §5). */
  reparse_issues: ParseIssue[];
  schema_version: string;
}

// --- Awaiting-recovery block (MASTER_SPEC Part 6 §3.2) -----------------------------------------
//
// Mirrors `backend/jobs/recovery.py::build_awaiting_block` verbatim — the block a job paused in
// `awaiting_recovery` carries on its envelope, typed opaque (`{ [key]: unknown }`) in the generated
// schema. Note the one shape difference from a *refusal*: there, `UnresolvedScenario.options` is a
// flat list of choice **codes**; here each option is enriched into an object carrying that same
// code plus the parameter names the Recovery Engine actually reads. Enrichment only — the service
// adds and drops nothing, so the honest, pair-specific option list computed by pre-flight survives
// intact (no `non_periodic` offered for a POSCAR target, because pre-flight never offered it).

/** One choice a paused job would accept, with the parameters it consumes — Part 6 §3.2. */
export interface RecoveryOption {
  /** Machine choice code, e.g. "bounding_box" — the token a caller passes back. */
  choice: string;
  /** `{ param_name: human description }`; absent when the choice takes no parameters. */
  parameters_schema?: Record<string, string>;
}

/** An unresolved scenario as the *pause* carries it — like {@link UnresolvedScenario}, richer options. */
export interface AwaitingScenario {
  scenario: string;
  path: string | null;
  detail: string | null;
  options: RecoveryOption[];
}

/**
 * The `awaiting_recovery` block. `draft_report` is the pre-flight Conversion Report
 * (`stage: "preflight"`, `status: "awaiting_recovery"`) — the "here is what happens once you
 * decide" preview — and `unresolved_scenarios` is what still needs deciding.
 */
export interface AwaitingRecoveryBlock {
  draft_report: ConversionReport;
  unresolved_scenarios: AwaitingScenario[];
}

// --- Error envelope (MASTER_SPEC Part 6 §6) ----------------------------------------------------
//
// The single non-2xx body every `/v1` error path renders — a raised ApiError, a request-validation
// failure, an unexpected exception, an unmatched route (`backend/models.py::ErrorEnvelope`). The
// client writes exactly one error-handling branch against it. `code` is a stable machine string
// shown verbatim (never localized, never paraphrased); `request_id` is the bridge to server logs.

/** The inner `error` object — Part 6 §6 `ErrorBody`. */
export interface ErrorBody {
  /** Stable machine string, e.g. "UNKNOWN_FORMAT" — rendered verbatim. */
  code: string;
  message: string;
  /** Structured specifics (offending field, allowed values, …); `{}` when none. */
  details: Record<string, unknown>;
  request_id: string;
  documentation_url: string;
}

/** The whole non-2xx body: `{ error: { … } }` — Part 6 §6 `ErrorEnvelope`. */
export interface ErrorEnvelope {
  error: ErrorBody;
}
