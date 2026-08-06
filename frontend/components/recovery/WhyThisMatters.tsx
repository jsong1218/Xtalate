import { whyForScenario } from "@/lib/recovery/why";

/**
 * The "Why does this matter?" progressive disclosure (MASTER_SPEC Part 7 §3.1, deliverable 6; slice
 * M31-S3).
 *
 * The three plain-language options on the card are enough for a non-expert to act. This is what they
 * open when they want the scientific stakes — what the missing thing is, that a fabricated value is
 * an artifact rather than recovered data, and which choices are safe for which purposes. It is a
 * native `<details>`: collapsed by default so it never becomes a wall of prose in the decision path,
 * keyboard-operable and screen-reader-announced for free.
 *
 * The copy comes verbatim from `lib/recovery/why.ts`, whose coverage is lint-enforced. A scenario
 * with no copy (a future plugin's) renders nothing rather than an empty disclosure.
 */
export function WhyThisMatters({ scenario }: { scenario: string }) {
  const why = whyForScenario(scenario);
  if (!why) return null;

  return (
    <details data-testid="why-this-matters" className="group text-sm">
      <summary className="cursor-pointer list-none text-muted underline decoration-dotted underline-offset-2 hover:text-strong [&::-webkit-details-marker]:hidden">
        {why.question}
      </summary>
      <div className="mt-2 space-y-2 border-l-2 border-line pl-3 text-muted">
        {why.stakes.map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </div>
    </details>
  );
}
