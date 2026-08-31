/**
 * SSR-safe localStorage helpers for the QoL layer (UI redesign S4, D246; D-R6 — every QoL read/
 * write is client-side, never a new backend route or dependency).
 *
 * `localStorage` is a browser-only, quota- and policy-bound API: it can throw on access (privacy
 * mode, storage disabled), is `undefined` during SSR, and its reads must never break a render.
 * These helpers make the "try/catch around every read/write" rule (the slice plan's exact words)
 * true in one place, so the callers in `presets.ts` / `recents.ts` / the palette are plain data
 * code with no error plumbing. `STORAGE_PREFIX` is the `xtalate-` convention the theme and notify
 * providers already use — every key stays namespaced and greppable.
 */

/** The shared namespace prefix for every persisted client-side key. */
export const STORAGE_PREFIX = "xtalate-";

function isServer(): boolean {
  return typeof window === "undefined";
}

/**
 * Read a stored string, or `null` when unset, unavailable (SSR), or storage is blocked (privacy
 * mode / quota). Callers `JSON.parse`+validate the result themselves. Never throws.
 */
export function readStorage(key: string): string | null {
  if (isServer()) return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/**
 * Write a string. Best-effort — a blocked storage (quota, disabled) is detected and swallowed so a
 * QoL preference can *never* break a render or a navigation. Returns whether the write landed, so
 * a "did my preset save?" affordance can stay honest without throwing.
 */
export function writeStorage(key: string, value: string): boolean {
  if (isServer()) return false;
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** Remove a key (best-effort; used when a preset is deleted). */
export function removeStorage(key: string): void {
  if (isServer()) return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore — a blocked storage just cannot delete; reads treat it as absent anyway.
  }
}

/** The `xtalate-...` key for a bare name, kept consistent with the theme/notify keys. */
export function prefixedKey(name: string): string {
  return `${STORAGE_PREFIX}${name}`;
}

/**
 * Read a JSON value under `name`, validated by `isValid` (a type guard the caller provides, so a
 * hand-edited / stale / schema-migrated value is never trusted). Falls back to `fallback`.
 */
export function readJson<T>(name: string, isValid: (value: unknown) => value is T, fallback: T): T {
  const raw = readStorage(prefixedKey(name));
  if (raw === null) return fallback;
  try {
    const parsed: unknown = JSON.parse(raw);
    return isValid(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

/** Write a JSON value under `name`; returns whether it landed. */
export function writeJson(name: string, value: unknown): boolean {
  try {
    return writeStorage(prefixedKey(name), JSON.stringify(value));
  } catch {
    return false;
  }
}