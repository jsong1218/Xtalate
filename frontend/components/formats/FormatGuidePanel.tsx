import { formatGuide } from "@/lib/formats/guide";

/**
 * The editorial File Format Guide for one format (frontend redesign addendum §4.5) — the plain-
 * language half of a format page, rendered above the generated capability grid so a single page
 * tells the whole story: what the format is, who uses it, what it stores, and where it falls short.
 *
 * The content is first-party editorial prose keyed by `format_id` in {@link formatGuide}, never
 * derived from the capability declaration. A format the guide has no entry for — a third-party
 * plugin — gets an **honest fallback note** here instead of a fabricated blank: the note says no
 * extended guide exists and points at the capability grid, which stands on its own. That is the P6
 * seam on screen: a plugin format is still fully documented by its own declaration, just without
 * hand-written prose.
 */

/** A labelled bullet list; omitted entirely when the list is empty (never an empty heading). */
function GuideList({ heading, items }: { heading: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-strong">{heading}</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm text-body">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function FormatGuidePanel({
  formatId,
  formatName,
}: {
  formatId: string;
  formatName: string;
}) {
  const guide = formatGuide(formatId);

  if (guide === null) {
    return (
      <section
        data-testid="format-guide-fallback"
        aria-label={`About ${formatName}`}
        className="rounded-md border border-line bg-raised p-4 text-sm text-body"
      >
        No extended guide is available for {formatName} yet. The capability declaration below still
        describes exactly what this instance can read and write for it, field by field.
      </section>
    );
  }

  return (
    <section
      data-testid="format-guide"
      aria-label={`About ${formatName}`}
      className="space-y-6 rounded-md border border-line bg-raised p-5"
    >
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-strong">About this format</h2>
        <p className="text-base text-body">{guide.summary}</p>
        <p className="text-sm text-muted">{guide.context}</p>
      </div>

      <div className="grid gap-x-8 gap-y-6 sm:grid-cols-2">
        <GuideList heading="What it stores" items={guide.stores} />
        <GuideList heading="Typical use cases" items={guide.useCases} />
        <GuideList heading="Strengths" items={guide.advantages} />
        <GuideList heading="Trade-offs" items={guide.disadvantages} />
        <GuideList heading="Typical workflows" items={guide.workflows} />
        <GuideList heading="Common software" items={guide.commonSoftware} />
      </div>

      {guide.limitations.length > 0 ? (
        <div className="space-y-2 rounded-md border border-cb-warning/40 bg-cb-warning-bg p-4">
          <h3 className="text-sm font-semibold text-strong">Important limitations</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-body">
            {guide.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
