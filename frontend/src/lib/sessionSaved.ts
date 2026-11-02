/** Where the buyer was on a list page, kept per browser tab in sessionStorage,
 *  so coming back from the detail page (or a phone reloading a discarded tab)
 *  lands on the same filters, scroll position and opened homes. Each page owns
 *  one versioned key (`hb.<page>.v1`); a shape change bumps it for a clean
 *  reset, never a corrupt read. */
export function loadSaved<T extends object>(key: string): Partial<T> {
  try {
    return JSON.parse(sessionStorage.getItem(key) ?? "{}") as Partial<T>;
  } catch {
    return {};
  }
}

export function save<T extends object>(key: string, patch: Partial<T>): void {
  try {
    sessionStorage.setItem(key, JSON.stringify({ ...loadSaved<T>(key), ...patch }));
  } catch {
    // storage blocked (private window): the page just starts fresh next time
  }
}
