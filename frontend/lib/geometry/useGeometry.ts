"use client";

/**
 * Geometry query hooks (v1.6 M59-S2). Thin wrappers over the typed client's geometry queries
 * (Part 6 §7): the viewer (M60+) consumes `CanonicalGeometry` from `useFileGeometry` /
 * `useConversionGeometry` and feeds it to the loader — no second wire form, no export.
 */
import { useQuery } from "@tanstack/react-query";
import {
  conversionGeometryQuery,
  fileGeometryQuery,
} from "@/lib/api/queries";
import type { Schemas } from "@/lib/api/client";

export type CanonicalGeometry = Schemas["GeometryResponse"];

export interface GeometryState {
  status: "loading" | "error" | "ready";
  geometry?: CanonicalGeometry;
  error?: unknown;
}

export function useFileGeometry(fileId: string, frames?: string): GeometryState {
  const query = useQuery(fileGeometryQuery(fileId, frames));
  if (query.isError) {
    return { status: "error", error: query.error };
  }
  if (!query.data) {
    return { status: "loading" };
  }
  return { status: "ready", geometry: query.data };
}

export function useConversionGeometry(
  conversionId: string,
  side: "source" | "output",
  frames?: string
): GeometryState {
  const query = useQuery(conversionGeometryQuery(conversionId, side, frames));
  if (query.isError) {
    return { status: "error", error: query.error };
  }
  if (!query.data) {
    return { status: "loading" };
  }
  return { status: "ready", geometry: query.data };
}
