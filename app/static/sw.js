// HeavyTrack Enterprise - Service Worker (Offline-First App Shell)
const CACHE_NAME = 'acr-flota360-v2.1.0';
const STATIC_ASSETS = [
  '/',
  '/operador',
  '/mobile',
  '/static/css/style.css',
  '/static/js/offline-sync.js',
  '/static/manifest.json',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/apple-touch-icon.png',
  '/static/img/logo_acr360_white.png'
];

// Instalación y pre-cacheo de recursos críticos
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Cacheando App Shell para operación offline');
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activación y limpieza de caches antiguos
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[SW] Purgando cache obsoleto:', key);
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Intercepción de peticiones de red (Estrategia: Network First con fallback a Cache)
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Las peticiones API POST o SYNC no se cachean con SW (se manejan vía IndexedDB en offline-sync.js)
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/sync/batch')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        // Si hay red y es un asset estático, actualizar cache en segundo plano
        if (networkResponse && networkResponse.status === 200) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(async () => {
        // Si falla la red (Modo sin señal en obra), retornar desde cache
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) {
          return cachedResponse;
        }

        // Si es una navegación HTML y no hay red, servir la vista offline móvil
        if (event.request.headers.get('accept')?.includes('text/html')) {
          return caches.match('/mobile');
        }
      })
  );
});
