"use client";

/**
 * The M59-S2/S3 **render proof + spike harness**: a dev-only surface that mounts `StructureViewer`
 * against a chosen file's geometry endpoint. This is the minimal-mount evidence that a canonical
 * object renders from `/v1/files/{file_id}/geometry` with no intermediate format, plus the S3
 * scrub harness (the window links below drive client-side navigations so the S3 journey measures
 * heap across sequential mounts in one JS context). **Not** the Structure tab (that is M60) and
 * not a production surface: in a production build (`NODE_ENV === "production"`, as `next build`
 * bakes) the page renders a gate notice instead of the viewer.
 */
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { StructureViewer } from "@/components/StructureViewer";
import { useFileGeometry } from "@/lib/geometry/useGeometry";

/** The S3 scrub windows: ten 100-frame reads spread across a 10⁴-frame trajectory. */
const SCRUB_WINDOWS = [
  "0:100",
  "1000:1100",
  "2000:2100",
  "3000:3100",
  "4000:4100",
  "5000:5100",
  "6000:6100",
  "7000:7100",
  "8000:8100",
  "9000:9100",
];

export default function DevStructurePage() {
  const { file_id } = useParams<{ file_id: string }>();
  // The spike surface accepts an optional `?frames=start:end` window (S3 scrub measurement);
  // omitted, it defaults to frame 0 — the structure.
  const frames = useSearchParams().get("frames") ?? undefined;
  const { status, geometry, error } = useFileGeometry(file_id, frames);

  if (process.env.NODE_ENV === "production") {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-lg font-semibold text-strong">
          Dev-only spike surface
        </h1>
        <p className="mt-2 text-sm text-muted">
          This route is the M59-S2/S3 render proof and is not available in
          production builds. The Structure tab ships in M60.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-lg font-semibold text-strong">
        Structure render proof{" "}
        <span className="text-xs font-normal text-faint">
          (dev-only spike surface — M59-S2/S3)
        </span>
      </h1>
      <p className="mt-1 text-xs text-faint">
        Renders file <code className="rounded bg-well px-1">{file_id}</code>{" "}
        from its canonical geometry endpoint — no intermediate format, no export.
        {frames ? (
          <>
            {" "}
            <code className="rounded bg-well px-1">frames={frames}</code>
          </>
        ) : null}
      </p>
      <div className="mt-4">
        {status === "loading" ? (
          <p className="text-sm text-faint">Loading geometry…</p>
        ) : status === "error" ? (
          <p className="text-sm text-cb-fail">
            Could not load geometry: {String(error)}
          </p>
        ) : geometry ? (
          <>
            <StructureViewer
              geometry={geometry}
              label={`${geometry.source.format_id}${
                geometry.source.filename ? ` · ${geometry.source.filename}` : ""
              } · ${geometry.species.length} atoms · ${
                geometry.frames?.length ?? 0
              }/${geometry.frame_count} frames`}
              // M61-S3: the spike surface mounts the viewer over the full trajectory read target so
              // the frame-count scrubber + playback appear, and passes a fast play interval so a
              // playback heap-measurement journey crosses many windows quickly in one JS context.
              trajectorySource={{ kind: "file", fileId: file_id }}
              playIntervalMs={80}
            />
            {/* The S3 scrub harness: client-side window links so the spike journey measures heap
                across sequential mounts in one JS context (the M61 scrub story). */}
            <div className="mt-2 flex flex-wrap items-center gap-1">
              <span className="text-xs text-faint">scrub windows:</span>
              {SCRUB_WINDOWS.map((w) => (
                <Link
                  key={w}
                  href={`/dev/structure/${file_id}?frames=${w}`}
                  className={`rounded border px-1.5 py-0.5 text-xs hover:bg-raised ${
                    frames === w
                      ? "border-line-strong bg-well text-body"
                      : "border-line text-faint"
                  }`}
                >
                  {w}
                </Link>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </main>
  );
}
