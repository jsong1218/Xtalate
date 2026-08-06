import Markdown from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

/**
 * Renders a committed `docs/*.md` page (slice M34-S1).
 *
 * `remark-gfm` gives the corpus its tables, task lists, and fenced code; `rehype-slug` assigns each
 * heading an `id` from its text, so a `## UNKNOWN_FORMAT` section on the error reference is reachable
 * at `#unknown_format` — exactly the anchor the error envelope's `documentation_url` points at
 * (`{docs_base_url}#{code.lower()}`). That link resolving is what the M34-S1 coverage lint guards.
 *
 * The `prose` classes come from the Tailwind typography plugin; loss colors are never used here (this
 * is long-form documentation, not a report), so the `--cb-*` token system is untouched. In dark mode
 * `dark:prose-invert` flips the long-form text to light-on-dark; the code blocks stay dark in both
 * themes (a dark code block on a light or dark page is conventional and legible).
 */
export function DocMarkdown({ content }: { content: string }) {
  return (
    <article className="prose prose-slate max-w-none dark:prose-invert prose-pre:bg-slate-900 prose-pre:text-slate-100">
      <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]}>
        {content}
      </Markdown>
    </article>
  );
}
