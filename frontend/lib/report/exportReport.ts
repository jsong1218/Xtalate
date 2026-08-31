import { labelForPath, labelForScenario } from "@/lib/mapping";
import type {
  Assumption,
  ConversionReport,
  PreservedEntry,
  RemovedEntry,
  ReportWarning,
} from "./types";
import { OUTCOME_ORDER, OUTCOME_LABELS, buildReportRows } from "./grouping";

/**
 * Report export — Copy-as-JSON / Copy-as-Markdown (UI redesign S3, D245; design spec §5).
 *
 * Both serializers are **pure** functions of the report model already in hand (Part 7 §2: the
 * client never re-derives a report — it renders, and here serializes, what the engine produced).
 * They exist so the export is deterministic and unit-testable: the same report always yields the
 * same string, and every assertion in the tests runs against those strings, not the DOM.
 *
 * JSON is the faithful serialization: the report model verbatim, pretty-printed, so a reader can
 * diff it against the wire body. Markdown is the human rendering of the same facts — the S3
 * outcome-first order, the engine's verbatim reasons and descriptions, and the canonical field
 * path always beside the plain-language label (the machine-readable truth never dropped).
 */

/**
 * The report model as a stable, pretty-printed JSON document. The whole `ConversionReport` is the
 * export — nothing is filtered, reordered, or paraphrased, so a loss can never be serialized away.
 */
export function reportToJson(report: ConversionReport): string {
  return `${JSON.stringify(report, null, 2)}\n`;
}

/** A markdown bullet for one row, shared by the four outcome sections. */
function markdownRow(report: ConversionReport, row: ReturnType<typeof buildReportRows>[number]): string {
  switch (row.kind) {
    case "preserved": {
      const entry = row.entry as PreservedEntry;
      const detail = entry.detail ? ` — \`${entry.detail}\`` : "";
      return `- ${labelForPath(entry.path).label} \`${entry.path}\`${detail}`;
    }
    case "removed": {
      const entry = row.entry as RemovedEntry;
      return `- ${labelForPath(entry.path).label} \`${entry.path}\`: ${entry.reason}${
        entry.detail ? ` (\`${entry.detail}\`)` : ""
      }`;
    }
    case "assumed": {
      const entry = row.entry as Assumption;
      const scenario = labelForScenario(entry.scenario);
      const supplied = report.supplied
        .filter((s) => s.from_assumption === entry.id)
        .map((s) => `\`${s.path}\``)
        .join(", ");
      const fields = supplied ? ` — supplied ${supplied}` : "";
      return `- **${entry.id}** — ${scenario.label} (\`${entry.choice}\`): ${entry.description}${fields}`;
    }
    case "warned": {
      const entry = row.entry as ReportWarning;
      return `- [\`${entry.code}\`] ${entry.message}`;
    }
  }
}

/**
 * The report as a Markdown document — outcome-first (Assumed → Lost → Warned → Kept), every row
 * present, reasons and descriptions verbatim. The header states the source → target and the mode,
 * the same facts the rendered panel leads with.
 */
export function reportToMarkdown(report: ConversionReport): string {
  const rows = buildReportRows(report);
  const lines: string[] = [
    "# Conversion Report",
    "",
    `**${report.source.filename}** (\`${report.source.format_id}\`) → **${report.target.filename}** (\`${report.target.format_id}\`)`,
    "",
    `Mode \`${report.mode}\` · Status \`${report.status}\` · Report \`${report.report_id}\``,
    "",
  ];
  for (const outcome of OUTCOME_ORDER) {
    const sectionRows = rows.filter((row) => row.outcome === outcome);
    if (sectionRows.length === 0) continue;
    lines.push(`## ${OUTCOME_LABELS[outcome]} (${sectionRows.length})`);
    lines.push("");
    for (const row of sectionRows) lines.push(markdownRow(report, row));
    lines.push("");
  }
  return lines.join("\n");
}

/**
 * Copy `text` to the clipboard — `navigator.clipboard` when available (secure contexts, granted
 * permission), with a hidden-textarea `execCommand("copy")` fallback for non-secure contexts and
 * older engines. Returns whether the copy is believed to have succeeded; callers surface a
 * transient confirmation, never a modal error.
 */
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && typeof navigator.clipboard?.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Permission denied or a browser policy — fall through to the legacy path.
    }
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    textarea.remove();
    return ok;
  } catch {
    return false;
  }
}
