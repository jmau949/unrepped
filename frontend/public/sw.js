// The app registers no service worker. This file exists for a browser that
// still has one registered for this origin by whatever ran on this port before
// (a browser keeps polling /sw.js for it on every visit, and a leftover worker
// with a cache can even serve that other app's pages). The next poll installs
// this script in its place; it unregisters itself and reloads the open tabs, so
// they come back worker-free and the polling stops. main.tsx does the same from
// inside the page for a worker registered under any other name.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(
    self.clients
      .claim()
      .then(() => self.registration.unregister())
      .then(() => self.clients.matchAll({ type: "window" }))
      .then((tabs) => Promise.all(tabs.map((tab) => tab.navigate(tab.url).catch(() => null)))),
  );
});
