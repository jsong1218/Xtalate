"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AnalysisResults } from "@/components/AnalysisResults";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { Button } from "@/components/ui/Button";
import { useAnalysis } from "@/lib/api/useAnalysis";
import { useAnalysisPlugins } from "@/lib/api/usePlugins";

/**
 * The workspace's Analysis tab (UI redesign S2 reserved this seam, D244; v1.8 M70 fills it).
 *
 * Analysis is a Secondary Goal that attaches at a defined seam (**P6**): it reads a Canonical Object
 * and annotates its own namespace — it never converts or edits the file. This tab is a thin
 * presenter over that seam: it asks `GET /v1/plugins` which analysis plugins the instance has,
 * offers them, and runs the chosen one via `POST /v1/analyze`, rendering the namespaced results
 * through the generic {@link AnalysisResults} renderer. The tab holds **no** plugin knowledge and no
 * scientific logic (Part 1 §2) — it does not know what "composition" computes; it renders whatever
 * keys the plugin wrote.
 *
 * The empty case is first-class: an instance with no analysis plugins installed (the default — the
 * reference plugin ships as its own distribution) shows an honest "none installed" state, never a
 * broken picker. A plugin that runs and *fails* is a completed job whose report says so (D268), and
 * `AnalysisResults` renders that honestly rather than as a blank panel.
 */
export default function AnalysisTabPage() {
  const params = useParams<{ file_id: string }>();
  const fileId = params.file_id;

  const plugins = useAnalysisPlugins();
  const analysis = useAnalysis(fileId);
  const [selected, setSelected] = useState<string>("");

  // Default the picker to the first installed plugin once the roster arrives.
  useEffect(() => {
    if (plugins.status === "ready" && plugins.analysis.length > 0 && selected === "") {
      setSelected(plugins.analysis[0].name);
    }
  }, [plugins, selected]);

  const running = analysis.state.status === "running";

  return (
    <main className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Analysis</h1>
        <p className="max-w-2xl text-sm text-muted">
          Run an installed analysis plugin over this file. Analysis reads your structure and adds a
          namespaced set of results — it never converts or edits the file, and every result is shown
          exactly as the plugin reported it, including anything it could not compute.
        </p>
      </header>

      {plugins.status === "loading" ? (
        <p className="text-sm text-muted">Loading installed plugins…</p>
      ) : null}

      {plugins.status === "error" ? (
        <p className="text-sm text-cb-fail">Could not load the installed plugins for this instance.</p>
      ) : null}

      {plugins.status === "ready" && plugins.analysis.length === 0 ? (
        <div className="rounded-lg border border-line bg-raised p-4 text-sm text-body">
          <p className="font-medium text-strong">No analysis plugins are installed.</p>
          <p className="mt-1 text-muted">
            Analysis plugins ship as their own installable distributions. Once one is installed on
            this instance, it will appear here to run against your file.
          </p>
        </div>
      ) : null}

      {plugins.status === "ready" && plugins.analysis.length > 0 ? (
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-body">Analysis plugin</span>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={running}
              className="min-w-56 rounded-md border border-line bg-surface px-3 py-2 text-sm text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {plugins.analysis.map((plugin) => (
                <option key={plugin.name} value={plugin.name}>
                  {plugin.name} ({plugin.version})
                </option>
              ))}
            </select>
          </label>
          <Button onClick={() => selected && analysis.run(selected)} disabled={running || !selected}>
            {running ? "Running…" : "Run analysis"}
          </Button>
        </div>
      ) : null}

      {analysis.state.status === "running" ? (
        <p className="text-sm text-muted" role="status">
          Running <span className="font-mono">{analysis.state.plugin}</span> over this file…
        </p>
      ) : null}

      {analysis.state.status === "error" ? <ErrorEnvelope envelope={analysis.state.error} /> : null}

      {analysis.state.status === "ready" ? (
        <section aria-label="Analysis results" className="space-y-2">
          <h2 className="text-sm font-semibold text-strong">
            {analysis.state.report.plugin}{" "}
            <span className="font-normal text-muted">v{analysis.state.report.plugin_version}</span>
          </h2>
          <AnalysisResults
            pluginName={analysis.state.report.plugin}
            status={analysis.state.report.status}
            results={analysis.state.report.results}
            message={analysis.state.report.message}
          />
        </section>
      ) : null}
    </main>
  );
}
