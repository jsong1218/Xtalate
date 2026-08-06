import Link from "next/link";
import type { ReactNode } from "react";
import { DOC_PAGES } from "@/lib/docs/pages";

/**
 * Shell for the `/docs/*` static site (MASTER_SPEC Part 7 §1; slice M34-S1): a left nav generated
 * from the one page registry, and the rendered Markdown beside it. `min-w-0` lets wide content
 * (tables, code blocks) scroll inside the prose column instead of stretching the page.
 */
export default function DocsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-8 md:grid-cols-[12rem_minmax(0,1fr)]">
      <nav aria-label="Documentation" className="space-y-1 text-sm md:sticky md:top-8 md:self-start">
        <Link href="/docs" className="block font-semibold text-strong">
          Documentation
        </Link>
        {DOC_PAGES.map((page) => (
          <Link
            key={page.slug}
            href={`/docs/${page.slug}`}
            className="block text-muted hover:text-strong hover:underline"
          >
            {page.title}
          </Link>
        ))}
        <Link href="/" className="block pt-2 text-faint hover:text-strong hover:underline">
          ← Home
        </Link>
      </nav>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
