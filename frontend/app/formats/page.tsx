import Link from "next/link";
import type { Metadata } from "next";

/**
 * Formats (`/formats`) — an honest v0.6 placeholder (MASTER_SPEC Part 7; slice M28-S1).
 *
 * A browsable Capability Matrix — every format and what it can and cannot hold — is a v0.7 page. The
 * landing links here, so the link must resolve to something truthful rather than a 404: this states
 * plainly that the standalone browser is coming, and points to where the same information already
 * lives today — the pre-flight preview on the conversion screen, which shows exactly what a given
 * source → target pair will carry, drop, or need to recover.
 */
export const metadata: Metadata = {
  title: "Formats — Xtalate",
};

export default function FormatsPage() {
  return (
    <main className="space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight">Explore formats</h1>
      <p className="max-w-2xl text-slate-700">
        A browsable Capability Matrix — every supported format and exactly which canonical fields it
        can and cannot express — is coming in <strong>v0.7</strong>.
      </p>
      <p className="max-w-2xl text-slate-600">
        In the meantime, you don&rsquo;t have to guess: upload a file and the pre-flight preview
        shows, for the target you pick, precisely what will carry over, what will be dropped, and
        what would need a recovery choice.
      </p>
      <div className="flex flex-wrap items-center gap-4 pt-1">
        <Link
          href="/convert"
          className="inline-block rounded-md bg-slate-900 px-4 py-2 font-medium text-white"
        >
          Convert a file
        </Link>
        <Link href="/" className="text-slate-600 underline">
          Back to home
        </Link>
      </div>
    </main>
  );
}
