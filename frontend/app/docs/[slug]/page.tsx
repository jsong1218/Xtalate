import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocMarkdown } from "@/components/docs/DocMarkdown";
import { DOC_PAGES, getDocPage, readDocContent } from "@/lib/docs/pages";

/**
 * A single documentation page (`/docs/[slug]`, slice M34-S1). Statically generated from the page
 * registry — `next build` renders each committed `docs/*.md` at build time, so the site is the same
 * one source, rendered a second way. `dynamicParams = false` makes any slug outside the registry a
 * 404 rather than an attempt to read an arbitrary file.
 */
export function generateStaticParams(): { slug: string }[] {
  return DOC_PAGES.map((page) => ({ slug: page.slug }));
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const page = getDocPage(slug);
  if (!page) return {};
  return { title: `${page.title} — Xtalate docs`, description: page.description };
}

export default async function DocPageRoute({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const page = getDocPage(slug);
  if (!page) notFound();
  return <DocMarkdown content={readDocContent(page)} />;
}
