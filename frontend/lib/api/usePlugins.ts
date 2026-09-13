"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";

/**
 * `GET /v1/plugins` — the installed-plugin roster (v1.8 M70; MASTER_SPEC Part 7 §6).
 *
 * The instance reports what is installed across all three plugin kinds (parsers, exporters,
 * analysis); the Analysis tab reads it to offer exactly the analysis plugins this instance has. The
 * plain dev/CI gate installs none (the composition reference plugin ships as its own distribution,
 * present only in the Docker image / a local editable install), so the empty case is a first-class
 * state, not an error — the tab renders an honest "no analysis plugins installed", never a spinner.
 */

/** One roster row, verbatim from the endpoint (kind/name/version; format plugins add format_name). */
export interface PluginRow {
  kind: "parser" | "exporter" | "analysis";
  name: string;
  version: string;
  format_name: string | null;
}

export type PluginsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; analysis: PluginRow[] };

/** Fetch the roster and expose just the analysis plugins, sorted by name (the endpoint pre-sorts). */
export function useAnalysisPlugins(): PluginsState {
  const query = useQuery({
    queryKey: ["plugins"],
    queryFn: async ({ signal }) => {
      const { data, error } = await apiClient.GET("/v1/plugins", { signal });
      if (error) throw error;
      return data;
    },
  });

  if (query.isError) return { status: "error" };
  if (!query.data) return { status: "loading" };

  // The endpoint's response is an untyped object array on the wire (Part 6 §3.2 result shape); the
  // roster's fields are fixed by the plugins router, so we narrow to the known row shape here.
  const rows = (query.data.plugins ?? []) as unknown as PluginRow[];
  const analysis = rows.filter((row) => row.kind === "analysis");
  return { status: "ready", analysis };
}
