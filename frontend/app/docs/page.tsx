import type { Metadata } from "next";
import Link from "next/link";
import { DOC_PAGES } from "@/lib/docs/pages";

/**
 * Docs index (`/docs`) — the entry point to the static documentation site (slice M34-S1). It lists
 * the committed `docs/` corpus rendered under `/docs/*`; the content lives in Markdown, never here.
 */
export const metadata: Metadata = {
  title: "Documentation — Xtalate",
  description:
    "Xtalate documentation: quickstart, CLI reference, the /v1 API, the error reference, and more.",
};

export default function DocsIndexPage() {
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Documentation</h1>
        <p className="max-w-2xl text-body">
          Everything here is rendered from the project&rsquo;s committed Markdown — the same source
          the repository serves. Start with the quickstart, or jump to the reference you need.
        </p>
      </header>
      <ul className="space-y-4">
        {DOC_PAGES.map((page) => (
          <li key={page.slug} className="space-y-1">
            <Link href={`/docs/${page.slug}`} className="font-medium text-strong underline">
              {page.title}
            </Link>
            <p className="text-sm text-muted">{page.description}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
