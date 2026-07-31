import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * The docs site's page registry (MASTER_SPEC Part 7 §1; slice M34-S1).
 *
 * **One source, two renderings.** Each entry names a file in the committed `docs/` Markdown corpus —
 * the same files GitHub renders — which the `/docs/[slug]` route reads and renders at build time.
 * There is no second copy of the content: change a `docs/*.md` file and both renderings follow. This
 * list is the single authority the route's `generateStaticParams`, the index, and the nav all read,
 * so a page is added in exactly one place.
 *
 * Server-only (it uses `node:fs`): imported by the `/docs` server components, never by client code.
 */
export interface DocPage {
  /** URL segment under `/docs/` and the stable cross-link target used inside the Markdown. */
  slug: string;
  /** Human title shown in the nav, the index, and the browser tab. */
  title: string;
  /** File name within the `docs/` directory. */
  file: string;
  /** One-line summary shown on the docs index. */
  description: string;
}

export const DOC_PAGES: readonly DocPage[] = [
  {
    slug: "quickstart",
    title: "Quickstart",
    file: "quickstart.md",
    description: "Install Xtalate and run your first conversion — library, CLI, or HTTP service.",
  },
  {
    slug: "cli",
    title: "CLI reference",
    file: "cli.md",
    description: "Every xtalate command and flag: inspect, convert, validate, capabilities.",
  },
  {
    slug: "errors",
    title: "Error reference",
    file: "errors.md",
    description: "Every error-envelope code, what it means, and what to do about it.",
  },
  {
    slug: "self-hosting",
    title: "Self-hosting",
    file: "self-hosting.md",
    description: "Run your own instance: production compose, configuration, backups, and observability.",
  },
  {
    slug: "api",
    title: "API",
    file: "API.md",
    description: "The /v1 REST surface, its async-job model, and the one error envelope.",
  },
  {
    slug: "architecture",
    title: "Architecture",
    file: "ARCHITECTURE.md",
    description: "The single spine — parse → canonical model → export — and its advisory subsystems.",
  },
  {
    slug: "developer-guide",
    title: "Developer guide",
    file: "DEVELOPER_GUIDE.md",
    description: "Extending Xtalate with new formats and third-party plugins.",
  },
] as const;

/** The committed docs directory, resolved from the frontend project root (mounted at build/dev). */
const DOCS_DIR = resolve(process.cwd(), "..", "docs");

export function getDocPage(slug: string): DocPage | undefined {
  return DOC_PAGES.find((page) => page.slug === slug);
}

export function readDocContent(page: DocPage): string {
  return readFileSync(resolve(DOCS_DIR, page.file), "utf-8");
}
