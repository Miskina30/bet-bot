/**
 * Theme handling: one `dark` class on <html>, persisted to localStorage.
 *
 * The bootstrap script below runs *before first paint* (inline in <head>) so a
 * dark-mode analyst never sees a white flash. It is the only inline script in the
 * app, which is why next.config.ts allows 'unsafe-inline' for script-src.
 *
 * The selection is stored as `light` | `dark` | `system`; `system` follows
 * `prefers-color-scheme` live. Keyboard users get the same control: the toggle is
 * a real <button> that cycles the three states and announces what it did.
 */

export type ThemeChoice = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "academic-edge-theme";

/** Inline, dependency-free, and resilient to storage being unavailable. */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var k='${THEME_STORAGE_KEY}';var s=window.localStorage.getItem(k);var q=window.matchMedia('(prefers-color-scheme: dark)');var d=s==='dark'||(s!=='light'&&q.matches);var r=document.documentElement;if(d){r.classList.add('dark');}else{r.classList.remove('dark');}r.style.colorScheme=d?'dark':'light';}catch(e){}})();`;

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system";
}

export function readStoredTheme(): ThemeChoice {
  if (typeof window === "undefined") {
    return "system";
  }
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Resolves the choice to the class that should be applied. */
export function resolveDark(choice: ThemeChoice): boolean {
  if (choice === "dark") {
    return true;
  }
  if (choice === "light") {
    return false;
  }
  return systemPrefersDark();
}

/** Applies a choice to <html> and persists it. Safe to call repeatedly. */
export function applyTheme(choice: ThemeChoice): void {
  if (typeof window === "undefined") {
    return;
  }
  const dark = resolveDark(choice);
  const root = window.document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    /* Storage may be blocked (private mode); the current session still works. */
  }
}

/** Next choice when the toggle is pressed: light -> dark -> system -> light. */
export function nextThemeChoice(choice: ThemeChoice): ThemeChoice {
  if (choice === "light") {
    return "dark";
  }
  if (choice === "dark") {
    return "system";
  }
  return "light";
}

export function themeChoiceLabel(choice: ThemeChoice): string {
  if (choice === "light") {
    return "light";
  }
  if (choice === "dark") {
    return "dark";
  }
  return "system";
}