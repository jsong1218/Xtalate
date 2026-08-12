/**
 * The completion signal (v1.1 M39-S4, C1) — the Web UI half of "tell me when my conversion
 * finished." Two independent channels, both additive UX that touches no conversion data and
 * reports nothing about the science:
 *
 *  - **`playChime()`** — a short two-note tone **synthesized** with the WebAudio API. No audio
 *    file ships with the bundle (no weight, no copyright surface). Browsers block audio until a
 *    user gesture, so `unlockAudio()` must be called from a click — the Convert confirm — after
 *    which the one shared `AudioContext` stays usable even when the tab is backgrounded, exactly
 *    the "I clicked Convert and switched tabs" case.
 *  - **`notify(title, body)`** — the browser Notification API. Permission is requested only when
 *    the user first enables the signal (see `NotifyPreferenceProvider`), never on page load.
 *    Clicking the notification focuses the tab.
 *
 * Both degrade gracefully and independently (C1): notifications denied ⇒ the sound still plays;
 * tab muted ⇒ the notification still shows; neither available (SSR, an old browser, a privacy
 * mode) ⇒ the existing on-page completion state is unchanged. Every call is feature-detected and
 * never throws — the signal is best-effort by construction and must not break the page it adorns.
 */

// --- audio --------------------------------------------------------------------------------------

// One AudioContext per session, created lazily and shared by every chime. Created (and resumed)
// from the Convert click via `unlockAudio`, so it is usable when the job later completes in a
// backgrounded tab. Module-level state is deliberate: the context must outlive the page's
// components (the signal fires on the job page, the gesture that armed it happened on the file
// page). Tests exercise it through `vi.resetModules()` + a stubbed `AudioContext`.
let audioContext: AudioContext | null = null;

function audioSupported(): boolean {
  return typeof window !== "undefined" && typeof window.AudioContext !== "undefined";
}

/**
 * Arm the shared audio context from a user gesture. Safe to call on every Convert click: it is a
 * no-op once the context exists and is running. Browsers require the *gesture* — a click handler —
 * for the initial `resume()`; afterwards the context stays usable in backgrounded tabs.
 */
export function unlockAudio(): void {
  if (!audioSupported()) return;
  try {
    if (!audioContext) audioContext = new AudioContext();
    if (audioContext.state === "suspended") void audioContext.resume();
  } catch {
    // Audio is best-effort; a blocked context never breaks the page (C1 degrades to the
    // notification, or to nothing).
  }
}

/**
 * Play the completion chime — two short sine tones a rising fourth apart (E5 → A5), distinct from
 * transient UI feedback and short enough not to be noise. Fully synthesized; no audio asset.
 */
export function playChime(): void {
  unlockAudio();
  if (!audioContext) return;
  try {
    const now = audioContext.currentTime;
    _tone(audioContext, 659.25, now, 0.12, 0.18); // E5
    _tone(audioContext, 880.0, now + 0.13, 0.22, 0.16); // A5
  } catch {
    // Best-effort, as above.
  }
}

function _tone(
  ctx: AudioContext,
  frequency: number,
  start: number,
  duration: number,
  peak: number,
): void {
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = frequency;
  // A short attack and a longer exponential release: a bell-like blip, not a click.
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(peak, start + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain);
  gain.connect(ctx.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.05);
}

// --- notification -------------------------------------------------------------------------------

/** Feature-detect the Notification API (SSR-safe; jsdom lacks it, so unit tests stub it). */
export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/**
 * Request notification permission — called when the user **enables** the signal (the toggle's
 * click), never on page load. Returns whether notifications may be posted.
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (!notificationsSupported()) return false;
  try {
    const permission =
      Notification.permission === "default"
        ? await Notification.requestPermission()
        : Notification.permission;
    return permission === "granted";
  } catch {
    return false;
  }
}

/**
 * Post a completion notification. Requests permission only if the caller did not already (the
 * toggle-enable path normally does; this is the "first signal with it on" backstop). A denied
 * permission is a silent no-op — the sound still plays. Clicking the notification focuses the tab.
 */
export async function notify(title: string, body: string): Promise<void> {
  if (!notificationsSupported()) return;
  try {
    if (Notification.permission === "denied") return;
    if (Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") return;
    }
    const n = new Notification(title, { body });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    // Best-effort: a blocked notification never breaks the page.
  }
}

/**
 * The full completion signal: chime + notification, each degrading independently. Called once by
 * `useCompletionSignal` on the job page's non-terminal → terminal transition, only when the
 * persisted preference is on *and* the job was armed (see below). Fires on any terminal outcome —
 * completed, refused, failed, cancelled, expired — because the page already shows *which*; the
 * signal only says "it's done."
 */
export function signalCompletion(): void {
  playChime();
  void notify("Xtalate", "Your conversion finished.");
}

// --- the "armed" set: only a job the user just launched may signal ------------------------------

/**
 * The job page always loads cold: its poll query starts `undefined` and resolves to the job's real
 * state, so a *refresh* of — or a *shared link* to — an already-finished job looks byte-for-byte
 * like a fresh finish (`undefined → terminal`). Under the Tier-0 inline queue the just-submitted
 * job is *already* terminal by the time the page mounts, so we cannot tell "I just started this"
 * from "I reopened a done one" by job state alone — the distinguishing fact is out of band.
 *
 * So the Convert submit **arms** the returned job id here, and {@link useCompletionSignal} **consumes**
 * that arm on the job's first terminal transition: the signal fires once, for the conversion the
 * user actually launched, and a reload or a link-open (never armed, or already consumed) stays
 * silent. `sessionStorage` (not `localStorage`) scopes the arm to this browser tab, so the same job
 * URL opened in a new tab is not armed either. Best-effort and non-throwing, like the rest of this
 * module (private-mode storage failures degrade to "no signal", never a thrown error).
 */
const ARMED_STORAGE_KEY = "xtalate-armed-jobs";

function readArmed(): string[] {
  try {
    const raw = sessionStorage.getItem(ARMED_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeArmed(ids: string[]): void {
  try {
    sessionStorage.setItem(ARMED_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Persistence is best-effort; a storage failure simply means this finish won't signal.
  }
}

/** Arm a job id so its first terminal transition may signal — called from the Convert submit. */
export function armCompletionSignal(jobId: string): void {
  if (typeof window === "undefined") return;
  const armed = readArmed();
  if (!armed.includes(jobId)) writeArmed([...armed, jobId]);
}

/**
 * Consume a job id's arm: returns whether it was armed and clears it, so a given finish can signal
 * at most once even across remounts. An unarmed id (a reload, a shared link) returns `false`.
 */
export function consumeCompletionSignalArm(jobId: string): boolean {
  if (typeof window === "undefined") return false;
  const armed = readArmed();
  if (!armed.includes(jobId)) return false;
  writeArmed(armed.filter((id) => id !== jobId));
  return true;
}
