"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { IconButton } from "@/components/ui/IconButton";
import { useTheme, type ThemePreference } from "@/lib/theme/ThemeProvider";

/**
 * The three-state theme control (redesign D-B7): System · Light · Dark as a `role="group"` of
 * `aria-pressed` toggle buttons. Replaces the two-state `ThemeToggle`. The resolved theme is the
 * provider's business; this only shows and sets the *preference*.
 */
const OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string; icon: LucideIcon }> = [
  { value: "system", label: "Use system theme", icon: Monitor },
  { value: "light", label: "Use light theme", icon: Sun },
  { value: "dark", label: "Use dark theme", icon: Moon },
];

export function ThemeControl() {
  const { preference, setPreference } = useTheme();
  // The server renders preference "system" (no window) while a client may hold a stored choice, and
  // React does not patch attribute mismatches on hydration. Press nothing until mounted so server
  // and first client render agree; the right button presses right after.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return (
    <div role="group" aria-label="Theme" className="inline-flex items-center gap-1 rounded border border-wb-hairline p-1">
      {OPTIONS.map((o) => (
        <IconButton
          key={o.value}
          icon={o.icon}
          label={o.label}
          size={14}
          pressed={mounted && preference === o.value}
          onClick={() => setPreference(o.value)}
        />
      ))}
    </div>
  );
}
