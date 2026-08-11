"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { humanBytes } from "@/lib/format";
import { limitsQuery } from "@/lib/api/queries";

/**
 * The public-demo banner (v1.1 M39-S1, re-targeted S1b — the hosted demo).
 *
 * Shown **only** when `NEXT_PUBLIC_DEMO_BANNER` is set — the baked demo image sets it; a self-host
 * never renders the banner. It states the demo's posture up front rather than letting a visitor
 * discover it by hitting a limit (the Part 6 §5 "read before you hit it" rule, applied to the
 * surface itself): the demo is ephemeral, the cap is the *running instance's* real
 * `GET /v1/limits` value (never a hard-coded number — the same source the landing page and the
 * upload dropzone use, so the banner can never drift from the actual gate), and the escape hatch
 * is the same funnel copy the `413 FILE_TOO_LARGE` path uses: the free local path (CLI /
 * self-hosting), where no size limit exists.
 *
 * A client component on purpose: the flag is a `NEXT_PUBLIC_` value **inlined at build time**, and
 * the limits read must be live at request time — a server component in the layout would be baked
 * into statically prerendered pages at build (e.g. `/convert`, `○` in the build output), showing a
 * stale or absent cap. The query is `enabled`-gated on the flag, so an off banner makes **zero**
 * requests; when on, the cap renders after hydration, from the browser's same-origin `/v1` (the
 * same rewrite the rest of the UI uses).
 */
export function DemoBanner() {
  const enabled = process.env.NEXT_PUBLIC_DEMO_BANNER === "1";
  const { data: limits } = useQuery({ ...limitsQuery(), enabled });

  if (!enabled) return null;
  const maxUploadBytes = limits?.max_upload_bytes ?? null;

  return (
    <div
      data-testid="demo-banner"
      className="border-b border-line bg-well px-4 py-2 text-center text-xs text-muted"
    >
      <span className="font-medium text-strong">Public demo</span>
      {" · ephemeral — data is not retained"}
      {maxUploadBytes !== null ? ` · ${humanBytes(maxUploadBytes)} upload cap` : ""}
      {" · for larger files or private data, "}
      <Link
        href="/docs/self-hosting"
        className="underline underline-offset-2 hover:text-strong"
      >
        install the CLI or self-host
      </Link>
      .
    </div>
  );
}
