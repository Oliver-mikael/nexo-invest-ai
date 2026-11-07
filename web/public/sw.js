/*
 * Service worker de Nexo Invest AI.
 *
 * Política de caché deliberada:
 * - Shell de la aplicación (HTML, JS, CSS, iconos): cache-first con actualización en
 *   segundo plano. Nunca se cachean respuestas de /api.
 * - Navegación: red primero; si falla, la última copia del shell o /offline.html.
 * - /api: solo red. Los datos financieros y de sesión no se guardan en el
 *   dispositivo, así que cerrar sesión o limpiar datos no deja cifras en caché.
 *
 * La app distingue explícitamente entre datos disponibles sin conexión (el shell y
 * el informe ya abierto, en memoria) y datos que exigen red (todo lo demás).
 */

const VERSION = "nexo-v1";
const SHELL = ["/", "/offline.html", "/manifest.webmanifest", "/icons/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

function isAsset(url) {
  return url.pathname.startsWith("/assets/") || /\.(?:css|js|png|svg|woff2?)$/.test(url.pathname);
}

async function cacheFirst(request) {
  const cache = await caches.open(VERSION);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return cached || (await network) || Response.error();
}

async function networkFirst(request) {
  const cache = await caches.open(VERSION);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    const offline = await cache.match("/offline.html");
    if (offline) return offline;
    return new Response("Sin conexión", { status: 503, headers: { "Content-Type": "text/plain" } });
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request).catch(
        () =>
          new Response(
            JSON.stringify({
              error: {
                code: "offline",
                message: "Sin conexión: esta acción necesita red. Los datos financieros no se guardan en el dispositivo.",
              },
            }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
    return;
  }

  if (isAsset(url)) {
    event.respondWith(cacheFirst(request));
  }
});
