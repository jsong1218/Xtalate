"use client";

/**
 * The M59-S2 **render proof**: a dev-only spike surface that mounts `StructureViewer` against a
 * chosen file's geometry endpoint. This is the minimal-mount evidence that a canonical object
 * renders from `/v1/files/{file_id}/geometry` with no intermediate format — **not** the Structure
 * tab (that is M60) and not a production surface: in a production build (`NODE_ENV ===
 * "production"`, as `next build` bakes) the page renders a gate notice instead of the viewer.
 */
import { useParams } from "next/navigation";
import { StructureViewer } from "@/components/StructureViewer";
import { useFileGeometry } from "@/lib/geometry/useGeometry";

export default function DevStructurePage() {
  const { file_id } = useParams<{ file_id: string }>();
  const { status, geometry, error } = useFileGeometry(file_id);

  if (process.env.NODE_ENV === "production") {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-lg font-semibold text-slate-800">
          Dev-only spike surface
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          This route is the M59-S2 render proof and is not available in
          production builds. The Structure tab ships in M60.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-lg font-semibold text-slate-800">
        Structure render proof{" "}
        <span className="text-xs font-normal text-slate-400">
          (dev-only spike surface — M59-S2)
        </span>
      </h1>
      <p className="mt-1 text-xs text-slate-500">
        Renders file <code className="rounded bg-slate-100 px-1">{file_id}</code>{" "}
        from its canonical geometry endpoint — no intermediate format, no export.
      </p>
      <div className="mt-4">
        {status === "loading" ? (
          <p className="text-sm text-slate-500">Loading geometry…</p>
        ) : status === "error" ? (
          <p className="text-sm text-rose-600">
            Could not load geometry: {String(error)}
          </p>
        ) : geometry ? (
          <StructureViewer
            geometry={geometry}
            label={`${geometry.source.format_id}${
              geometry.source.filename ? ` · ${geometry.source.filename}` : ""
            } · ${geometry.species.length} atoms`}
          />
        ) : null}
      </div>
    </main>
  );
}
