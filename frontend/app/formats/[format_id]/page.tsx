import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { apiClient } from "@/lib/api/client";
import { FormatDetail } from "@/components/formats/FormatDetail";
import { formatRows, type FormatRow } from "@/lib/capabilities/matrix";
import type { CapabilitiesMap } from "@/lib/capabilities/types";

/**
 * A single format's detail page (`/formats/[format_id]`) — the read/write declaration behind one
 * grid row (MASTER_SPEC Part 7 §2.7; slice M33-S1). Like the grid, it is generated from
 * `GET /v1/capabilities` and describes the running instance, so a plugin format is addressable here
 * with no code change. A `format_id` the registry does not know is a genuine 404 (`notFound`), not a
 * fabricated empty page.
 */
export const dynamic = "force-dynamic";

async function loadFormat(formatId: string): Promise<FormatRow | null | undefined> {
  // `undefined` = the API was unreachable (distinct from a format that is genuinely absent, `null`).
  try {
    const { data } = await apiClient.GET("/v1/capabilities");
    if (!data) return undefined;
    return formatRows(data as CapabilitiesMap).find((r) => r.format_id === formatId) ?? null;
  } catch {
    return undefined;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ format_id: string }>;
}): Promise<Metadata> {
  const { format_id } = await params;
  const format = await loadFormat(format_id);
  const name = format ? format.format_name : format_id;
  return { title: `${name} — Formats — Xtalate` };
}

export default async function FormatDetailPage({
  params,
}: {
  params: Promise<{ format_id: string }>;
}) {
  const { format_id } = await params;
  const format = await loadFormat(format_id);

  if (format === null) notFound();

  return (
    <main className="space-y-6">
      <Link href="/formats" className="text-sm text-slate-600 underline">
        ← All formats
      </Link>
      {format ? (
        <FormatDetail format={format} />
      ) : (
        <p className="text-slate-700">
          This format&rsquo;s details are unavailable right now — this instance&rsquo;s API could not
          be reached.
        </p>
      )}
    </main>
  );
}
