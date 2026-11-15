import { ChevronDown } from "lucide-react";
import { Icon } from "./Icon";

/**
 * A native `<select>` with a mandatory label (redesign §9). Native on purpose: it is keyboard- and
 * screen-reader-complete for free and matches the instrument-panel register; the only styling is the
 * mono value, the hairline border and a Lucide chevron. `hideLabel` keeps the label in the
 * accessibility tree (sr-only) for compact strips such as stage 3's target/profile/repairs row.
 */
export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps {
  id: string;
  label: string;
  hideLabel?: boolean;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  className?: string;
}

export function Select({ id, label, hideLabel, value, onChange, options, disabled, className }: SelectProps) {
  return (
    <div className={className ? `inline-flex flex-col gap-1 ${className}` : "inline-flex flex-col gap-1"}>
      <label htmlFor={id} className={hideLabel ? "sr-only" : "text-xs text-muted"}>
        {label}
      </label>
      <span className="relative inline-flex items-center">
        <select
          id={id}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          className="h-8 appearance-none rounded border border-line bg-surface pl-2 pr-8 font-mono text-sm text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:cursor-not-allowed disabled:opacity-50"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="pointer-events-none absolute right-2 text-muted">
          <Icon icon={ChevronDown} size={14} />
        </span>
      </span>
    </div>
  );
}
