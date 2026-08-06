import "@testing-library/jest-dom/vitest";

// jsdom (opaque default origin) does not expose a usable Web Storage API, and reading either
// `window.localStorage` or Node's experimental `globalThis.localStorage` to feature-detect emits a
// runtime warning. So install a minimal in-memory `localStorage` *unconditionally* (never reading the
// existing slot — `Object.defineProperty` writes, so no getter fires and no warning is emitted). Real
// browsers have Storage natively; the theme provider (lib/theme) persists the user's light/dark
// choice here, and its tests rely on this to exercise persistence. Defined on both the test global
// and `window` so a bare `localStorage` reference resolves regardless of which is the global scope.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}
const memoryStorage = new MemoryStorage();
const storageDescriptor = { value: memoryStorage, configurable: true, writable: false };
Object.defineProperty(globalThis, "localStorage", storageDescriptor);
if (typeof window !== "undefined" && window !== (globalThis as unknown)) {
  Object.defineProperty(window, "localStorage", storageDescriptor);
}
