import Link from "next/link";
import { CapabilityGlyph } from "./capabilityGlyph";
import { cellLevel, formatRows, matrixFields, type FormatRow } from "@/lib/capabilities/matrix";
import type { CapabilitiesMap } from "@/lib/capabilities/types";

/**
 * The Capability Matrix as a browsable grid (MASTER_SPEC Part 7 §2.7; slice M33-S1).
 *
 * Rows are formats, columns are canonical fields, cells are the per-direction (read/write)
 * capability level. **Everything is generated from the `capabilities` map** — there is no hard-coded
 * format or field list here (see `lib/capabilities/matrix.ts`), so the grid can never drift from the
 * running instance's registry and an installed plugin format appears with zero UI changes: the P6
 * payoff on screen. The matrix is wide, so it lives in its own horizontal-scroll container — the page
 * body never scrolls sideways.
 *
 * A cell shows one glyph per direction the format declares, in the §4 loss vocabulary
 * (`capabilityGlyph.tsx`); a format that lacks a direction entirely omits that glyph rather than
 * faking a level for a direction it does not have. The row header links to the format's detail page.
 */

function CapabilityCell({ row, path }: { row: FormatRow; path: string }) {
  const read = cellLevel(row.read, path);
  const write = cellLevel(row.write, path);
  return (
    <td className="border-t border-slate-100 px-3 py-2 align-top">
      <span className="flex flex-col gap-0.5">
        {read !== null ? <CapabilityGlyph direction="read" level={read} /> : null}
        {write !== null ? <CapabilityGlyph direction="write" level={write} /> : null}
      </span>
    </td>
  );
}

export function FormatsGrid({ capabilities }: { capabilities: CapabilitiesMap }) {
  const rows = formatRows(capabilities);
  const fields = matrixFields(capabilities);

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">
          Capability Matrix: for each format, which canonical fields it can read and write.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 bg-white px-3 py-2 font-semibold text-slate-900">
              Format
            </th>
            {fields.map((field) => (
              <th
                key={field.path}
                scope="col"
                className="whitespace-nowrap px-3 py-2 font-medium text-slate-600"
              >
                {field.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.format_id}>
              <th
                scope="row"
                className="sticky left-0 whitespace-nowrap border-t border-slate-100 bg-white px-3 py-2 font-medium"
              >
                <Link href={`/formats/${row.format_id}`} className="text-slate-900 underline">
                  {row.format_name}
                </Link>
              </th>
              {fields.map((field) => (
                <CapabilityCell key={field.path} row={row} path={field.path} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
