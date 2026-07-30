import type { Metadata } from "next";
import Link from "next/link";
import { HistoryTable } from "@/components/history/HistoryTable";

/**
 * History (`/history`) — the durable list of past conversions (MASTER_SPEC Part 7 §2.6; slice
 * M33-S2). It puts one of the project's promises on screen: **reports outlive bytes**. A conversion
 * stays listed with its full report long after — and even because — its source upload is deleted;
 * "expired" is a rendered state with its explanation, never a surprise 404/410, and the list is
 * bounded (a record leaves history only when it passes report retention, not lingering as a husk).
 *
 * The page is a thin server shell: the table is a client component (cursor pagination + row actions
 * are interactive), and every load-bearing decision lives in the tested pieces it composes.
 */
export const metadata: Metadata = {
  title: "History — Xtalate",
};

export default function HistoryPage() {
  return (
    <main className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">History</h1>
        <p className="max-w-2xl text-slate-700">
          Every conversion this instance has run, newest first — with the loss summary visible on
          each row. A conversion&rsquo;s report stays readable even after its uploaded source file
          expires or is deleted.
        </p>
        <Link href="/" className="inline-block text-sm text-slate-600 underline">
          ← Home
        </Link>
      </header>

      <HistoryTable />
    </main>
  );
}
