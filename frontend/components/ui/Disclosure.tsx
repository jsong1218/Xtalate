import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

/**
 * A controlled disclosure (redesign §9): a header button that owns `aria-expanded` /
 * `aria-controls`, and a `role="region"` panel named by that header, mounted only while open. The
 * ledger's stage headers (S2) and "Show N more absent fields" (S2) are built on it. Controlled on
 * purpose — the ledger derives which stage is open from job state and the URL, so the component
 * never keeps its own open flag.
 */
export interface DisclosureProps {
  id: string;
  open: boolean;
  onToggle: () => void;
  summary: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Disclosure({ id, open, onToggle, summary, children, className }: DisclosureProps) {
  const summaryId = `${id}-summary`;
  const panelId = `${id}-panel`;
  return (
    <div className={className}>
      <button
        type="button"
        id={summaryId}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={onToggle}
        className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm text-strong hover:bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
      >
        <Icon icon={ChevronRight} size={14} className={open ? "rotate-90 transition-transform" : "transition-transform"} />
        <span className="min-w-0 flex-1">{summary}</span>
      </button>
      {open ? (
        <div id={panelId} role="region" aria-labelledby={summaryId} className="px-2 pb-3">
          {children}
        </div>
      ) : null}
    </div>
  );
}
