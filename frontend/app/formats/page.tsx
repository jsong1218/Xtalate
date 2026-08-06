import type { Metadata } from "next";
import Link from "next/link";
import { apiClient } from "@/lib/api/client";
import { FormatsGrid } from "@/components/formats/FormatsGrid";
import { LossTag } from "@/components/loss/icons";
import type { CapabilitiesMap } from "@/lib/capabilities/types";

/**
 * Formats (`/formats`) — the Capability Matrix as a browsable grid (MASTER_SPEC Part 7 §2.7; slice
 * M33-S1). It replaces the v0.6 honest placeholder and is the destination of the landing page's
 * "Explore formats" link.
 *
 * The grid is **generated from `GET /v1/capabilities`** at request time, so it describes the running
 * instance's registry — a self-hosted instance with a plugin format shows that format here with no
 * code change (the P6 payoff on screen). Server Component so the matrix paints fast and statically
 * (Part 7 §5.3); `force-dynamic` because capabilities are a runtime fact of *this* instance, never a
 * build-time constant (the same reason the landing figures are dynamic).
 */
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Formats — Xtalate",
};

async function loadCapabilities(): Promise<CapabilitiesMap | null> {
  try {
    const { data } = await apiClient.GET("/v1/capabilities");
    return (data as CapabilitiesMap | undefined) ?? null;
  } catch {
    return null;
  }
}

export default async function FormatsPage() {
  const capabilities = await loadCapabilities();

  return (
    <main className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Formats</h1>
        <p className="max-w-2xl text-body">
          Every supported format and exactly which canonical fields it can <strong>read</strong> and{" "}
          <strong>write</strong>. This grid is generated from this instance&rsquo;s own registry, so
          it always matches what the converter can actually do.
        </p>
      </header>

      {capabilities ? (
        <>
          {/* The glyph key — the §4 loss vocabulary, taught once so the grid needs no repetition. */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted">
            <span className="font-medium text-faint">Each cell:</span>
            <span>
              <span className="font-mono text-xs text-faint">R</span> reads /{" "}
              <span className="font-mono text-xs text-faint">W</span> writes
            </span>
            <LossTag kind="preserved">Full</LossTag>
            <LossTag kind="assumption">Partial (see the format for the condition)</LossTag>
            <LossTag kind="absent-format">None</LossTag>
          </div>
          <FormatsGrid capabilities={capabilities} />
        </>
      ) : (
        <div className="space-y-4">
          <p className="text-body">
            The format list is unavailable right now — this instance&rsquo;s API could not be reached.
          </p>
          <Link href="/" className="text-muted underline">
            Back to home
          </Link>
        </div>
      )}
    </main>
  );
}
