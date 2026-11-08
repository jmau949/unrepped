/** Where the device is, or null when the browser has nothing to give: no
 *  geolocation at all (a plain-HTTP page has none outside localhost), permission
 *  refused, or no fix inside the timeout. Never throws — callers fall back. */
export function currentPosition(timeoutMs = 8000): Promise<{ lat: number; lon: number } | null> {
  if (typeof navigator === "undefined" || !navigator.geolocation) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => resolve(null),
      { timeout: timeoutMs, maximumAge: 60_000 },
    );
  });
}
