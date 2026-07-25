/**
 * The client-side pre-flight preview — presence × target write-capability (MASTER_SPEC Part 3 §4.3,
 * Part 7 §2; slice M28-S2).
 *
 * When a user picks a target, the UI overlays *what that conversion would carry, drop, or need to
 * recover* — before submitting anything. This is the client mirror of the engine's pre-flight diff
 * (`src/xtalate/conversion/preflight.py`), computed from the same two inputs: the Discovery Report's
 * per-field presence and the target format's write-side `FormatCapabilities`. It is a **preview**,
 * not the authoritative report: the real conversion produces the binding `ConversionReport`, and if
 * this overlay were ever cut the page would simply submit and render that draft (the slice cut line).
 * So it deliberately mirrors only the engine's two *always-triggered*, choice-independent rules and
 * names itself a prediction — it never claims to be the engine's verdict.
 *
 * The three buckets, matching `build_preflight_from_presence`:
 *
 * * **carry** — a source-present field the target can write: `FULL`, or `PARTIAL` (kept, with the
 *   declared condition surfaced verbatim as the caveat — always shown, never silently assumed).
 * * **drop** — a source-present field the target cannot write: `NONE`, *including any path the
 *   target does not declare at all* (undeclared defaults to `NONE`, "cannot express it", Part 3
 *   §4.3). Getting that default wrong is the classic divergence — a naive "not on a drop-list ⇒
 *   carry" would silently promise a field the exporter then drops.
 * * **recover** — a target `required_field` **absent** on the source (→ `missing_lattice` and its
 *   catalog siblings), or a trajectory whose `frame_count` exceeds the target's `max_frames`
 *   (→ `frame_selection`). A required field that *is* present carries and never appears here — the
 *   other divergence a wrong intersection produces (listing every required field as "needs recovery"
 *   regardless of presence).
 *
 * What this preview intentionally does **not** predict — because resolving them is engine work, not a
 * capability lookup, and doing it here would reimplement scientific logic in the client (Part 7 §2):
 * the `constraint_representation` PARTIAL-subset choice, the partial-occupancy warning, and the
 * opt-in fabricative scenarios (velocity/mass *emission*, which fire only on a user recovery choice).
 * Those surface honestly in the actual Conversion Report the conversion returns. The preview is the
 * fast, always-true skeleton; the report is the whole truth.
 */

import type { CapabilityLevel, FormatCapabilities } from "@/lib/capabilities/types";
import { labelForPath, labelForScenario } from "@/lib/mapping";
import type { DiscoveryReport } from "@/lib/report/types";

export type PreflightFate = "carry" | "drop" | "recover";

export interface PreflightItem {
  /** Canonical field path (carry/drop always; recover when a missing field is the trigger). */
  path: string | null;
  /** Plain-language label, resolved through `lib/mapping.ts` (never inline). */
  label: string;
  fate: PreflightFate;
  /** PARTIAL caveat (verbatim), drop reason, or recovery explanation. */
  detail: string | null;
  /** Recovery scenario code (recover items only) — the mapping key and disclosure handle. */
  scenario?: string;
}

export interface PreflightPreview {
  targetFormatId: string;
  targetFormatName: string;
  carry: PreflightItem[];
  drop: PreflightItem[];
  recover: PreflightItem[];
}

// `atoms.atomic_numbers` is a derived mirror of `atoms.symbols` (Part 2 §3.3), reconstituted by any
// symbol-writing format — excluded from the diff exactly as the engine excludes it.
const DERIVED_PATHS = new Set(["atoms.atomic_numbers"]);

// Target required-field → the recovery scenario that supplies it (mirrors the engine's
// `_REQUIRED_FIELD_SCENARIOS`). An unlisted required field falls back to a generic scenario code.
const REQUIRED_FIELD_SCENARIOS: Record<string, string> = {
  "cell.lattice_vectors": "missing_lattice",
  "atoms.symbols": "missing_species",
  "dynamics.velocities": "missing_velocities",
  "atoms.masses": "missing_masses",
  "electronic.total_energy": "missing_energy",
};

/**
 * Map a presence path to the capability key that governs it. A dynamic custom key arrives as
 * `user_metadata.custom_per_frame['xyz:comment']` but capabilities are declared at the container
 * level, so the `['key']` suffix is stripped for the lookup — mirrors the engine's `capability_path`.
 * Omitting this strip is a silent divergence: the bracketed path misses every declaration and every
 * carried custom value would be mis-predicted as dropped.
 */
export function capabilityPath(presencePath: string): string {
  const bracket = presencePath.indexOf("[");
  return bracket === -1 ? presencePath : presencePath.slice(0, bracket);
}

/**
 * Compute the pre-flight preview of a Discovery Report against one target's **write** capabilities.
 * Pure: reads presence + capabilities and returns data, exactly as the engine's pre-flight is pure.
 */
export function buildPreflightPreview(
  discovery: DiscoveryReport,
  target: FormatCapabilities,
): PreflightPreview {
  const carry: PreflightItem[] = [];
  const drop: PreflightItem[] = [];
  const recover: PreflightItem[] = [];

  // 1. Source-present fields × target write-capability. An undeclared container defaults to NONE.
  for (const entry of discovery.fields) {
    if (entry.status !== "present" && entry.status !== "mixed") continue;
    if (DERIVED_PATHS.has(entry.path)) continue;

    const container = capabilityPath(entry.path);
    const cap = target.fields[container];
    const level: CapabilityLevel = cap?.level ?? "none";
    const label = labelForPath(entry.path).label;

    if (level === "full") {
      carry.push({ path: entry.path, label, fate: "carry", detail: null });
    } else if (level === "partial") {
      // The condition is always surfaced, never silently assumed to hold (Part 3 §4.3, D19).
      carry.push({ path: entry.path, label, fate: "carry", detail: cap?.notes ?? null });
    } else {
      const reason = cap?.notes ?? `${target.format_name} cannot store this field.`;
      drop.push({ path: entry.path, label, fate: "drop", detail: reason });
    }
  }

  // 2. Required-but-absent → recovery. Presence is consulted per field: a required field that is
  //    *present* carried in step 1 and must not reappear here.
  const statusByPath = new Map(discovery.fields.map((f) => [f.path, f.status]));
  for (const required of target.required_fields) {
    if (DERIVED_PATHS.has(required)) continue;
    const status = statusByPath.get(required);
    if (status === "present") continue; // present ⇒ carries; only absent/mixed/unknown recover.
    const scenario = REQUIRED_FIELD_SCENARIOS[required] ?? "missing_required_field";
    recover.push({
      path: required,
      label: labelForPath(required).label,
      fate: "recover",
      scenario,
      detail: `${target.format_name} requires this; it is ${status ?? "absent"} on the source.`,
    });
  }

  // 3. Trajectory too long for a single-structure (or frame-capped) target → frame_selection.
  const frameCount = discovery.structure.frame_count;
  if (
    target.max_frames !== null &&
    typeof frameCount === "number" &&
    frameCount > target.max_frames
  ) {
    recover.push({
      path: null,
      label: labelForScenario("frame_selection").label,
      fate: "recover",
      scenario: "frame_selection",
      detail: `${frameCount} frames → ${target.format_name} holds at most ${target.max_frames}.`,
    });
  }

  return {
    targetFormatId: target.format_id,
    targetFormatName: target.format_name,
    carry,
    drop,
    recover,
  };
}
