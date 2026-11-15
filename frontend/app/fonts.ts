import localFont from "next/font/local";

/**
 * The type system (redesign D-B6): IBM Plex Sans (chrome), Plex Mono (every number, path and
 * identifier via `DataValue`) and Plex Serif (stage-5 headline/lede/footnotes and the wordmark).
 * One superfamily with shared metrics, self-hosted from `app/fonts/` (Latin1 subset, two weights
 * each, OFL-1.1 — see `app/fonts/LICENSE-OFL.txt`), served from `/_next/static` with immutable
 * caching; nothing is fetched at runtime. Each family is exposed as a CSS variable on `<html>`
 * (see `app/layout.tsx`) and aliased in `tailwind.config.ts` (`font-sans` / `font-mono` /
 * `font-serif`). Glyphs outside Latin1 (Greek α β γ, for example) fall through to the system
 * fallback in the same stack.
 */
export const plexSans = localFont({
  src: [
    { path: "./fonts/IBMPlexSans-Regular-Latin1.woff2", weight: "400", style: "normal" },
    { path: "./fonts/IBMPlexSans-SemiBold-Latin1.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-sans",
  display: "swap",
});

export const plexMono = localFont({
  src: [
    { path: "./fonts/IBMPlexMono-Regular-Latin1.woff2", weight: "400", style: "normal" },
    { path: "./fonts/IBMPlexMono-Medium-Latin1.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-mono",
  display: "swap",
});

export const plexSerif = localFont({
  src: [
    { path: "./fonts/IBMPlexSerif-Regular-Latin1.woff2", weight: "400", style: "normal" },
    { path: "./fonts/IBMPlexSerif-SemiBold-Latin1.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-serif",
  display: "swap",
});

/** The class list that puts all three `--font-*` variables on `<html>`. */
export const fontClassName = `${plexSans.variable} ${plexMono.variable} ${plexSerif.variable}`;
