"use client";

import { useParams } from "next/navigation";
import { StructureTab } from "@/components/StructureTab";
import { useFileGeometry } from "@/lib/geometry/useGeometry";
import { useInspection } from "@/lib/api/useInspection";

/**
 * The workspace's Structure tab (UI redesign S2, D244) — the M60–M63 `StructureTab` given its own
 * tab slot (design spec §3, D-R1): the file's own geometry from `GET /v1/files/{id}/geometry`
 * (D232), mounted unchanged with the honest loading/expired/error states it owns. S5 finishes the
 * promotion (the dev spike goes away); S2 just moves the surface here.
 */
export default function StructureTabPage() {
  const params = useParams<{ file_id: string }>();
  const fileId = params.file_id;

  const fileGeometry = useFileGeometry(fileId);
  // The viewer label is the source filename when inspection knows it (one fetch, deduped with the
  // rail); the geometry itself never depends on it.
  const inspection = useInspection(fileId);
  const label = inspection.status === "ready" ? inspection.report.file.filename : undefined;

  return (
    <main>
      <StructureTab
        geometryState={fileGeometry}
        label={label}
        trajectorySource={{ kind: "file", fileId }}
      />
    </main>
  );
}
