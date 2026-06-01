const CACHE = 'flockiq-v1';
const STATIC_ASSETS = [
  '/static/css/tailwind.output.css',
  '/static/css/skeletons.css',
  '/static/js/htmx.min.js',
  '/static/js/alpine.min.js',
  '/static/js/chart.min.js',
  '/static/js/app.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Static assets: cache first
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(e.request).then(r => r || fetch(e.request))
    );
    return;
  }

  // API calls: network first, cache fallback
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() => caches.match(e.request))
    );
    return;
  }

  // Pages: network first
  e.respondWith(
    fetch(e.request).catch(() => caches.match('/'))
  );
});

// Background sync for offline form submissions
self.addEventListener('sync', e => {
  if (e.tag === 'sync-mortality') e.waitUntil(syncQueue('mortality'));
  if (e.tag === 'sync-eggs')     e.waitUntil(syncQueue('eggs'));
  if (e.tag === 'sync-feed')     e.waitUntil(syncQueue('feed'));
  if (e.tag === 'sync-water')    e.waitUntil(syncQueue('water'));
});

async function syncQueue(type) {
  const db = await openDB();
  const tx = db.transaction(type, 'readonly');
  const items = await tx.objectStore(type).getAll();

  for (const item of items) {
    try {
      await fetch(item.url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': item.csrfToken,
        },
        body: JSON.stringify(item.data),
      });
      const delTx = db.transaction(type, 'readwrite');
      await delTx.objectStore(type).delete(item.id);
    } catch (err) {
      console.error('Sync failed for', type, err);
    }
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('flockiq-offline', 1);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      ['mortality', 'eggs', 'feed', 'water'].forEach(store => {
        if (!db.objectStoreNames.contains(store)) {
          db.createObjectStore(store, { keyPath: 'id', autoIncrement: true });
        }
      });
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}
