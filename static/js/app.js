// FlockIQ — Global Alpine.js app state + HTMX configuration

function flockApp() {
  return {
    online: navigator.onLine,
    pinned: false,
    mobileMenuOpen: false,
    toasts: [],

    initApp() {
      window.addEventListener('online',  () => { this.online = true; });
      window.addEventListener('offline', () => { this.online = false; });

      // HTMX → Alpine toast bridge
      document.body.addEventListener('showToast', (e) => {
        this.addToast(e.detail.message || e.detail, e.detail.type || 'success');
      });

      // Django messages bridge (from base.html script tag)
      this.$nextTick(() => {
        const el = document.getElementById('django-messages-data');
        if (el) {
          try {
            const msgs = JSON.parse(el.textContent || '[]');
            msgs.forEach(m => this.addToast(m.message, m.type));
          } catch (_) {}
        }
      });

      // Service worker
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/js/sw.js').catch(() => {});
      }
    },

    addToast(message, type = 'success') {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, message: message || 'Done', type, visible: true });
      setTimeout(() => this.removeToast(id), 4000);
    },

    removeToast(id) {
      const toast = this.toasts.find(t => t.id === id);
      if (toast) toast.visible = false;
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, 200);
    },
  };
}

// HTMX configuration
document.addEventListener('DOMContentLoaded', () => {
  if (typeof htmx !== 'undefined') {
    htmx.config.defaultSwapStyle = 'innerHTML';
    htmx.config.historyCacheSize = 0;
  }
});

// HTMX showToast event relay (for HX-Trigger header responses)
document.addEventListener('showToast', (e) => {
  window.dispatchEvent(new CustomEvent('show-toast', { detail: e.detail }));
});

// ── Offline queue manager ────────────────────────────────────────────────────

function offlineQueue() {
  return {
    async saveToQueue(type, url, data, csrfToken) {
      const db = await this.openDB();
      const tx = db.transaction(type, 'readwrite');
      await tx.objectStore(type).add({ url, data, csrfToken, savedAt: Date.now() });

      if ('serviceWorker' in navigator && 'SyncManager' in window) {
        const reg = await navigator.serviceWorker.ready;
        await reg.sync.register(`sync-${type}`);
      }
    },

    openDB() {
      return new Promise((resolve, reject) => {
        const req = indexedDB.open('flockiq-offline', 1);
        req.onsuccess = e => resolve(e.target.result);
        req.onerror = reject;
      });
    },
  };
}

// Intercept HTMX requests when offline
document.addEventListener('htmx:beforeRequest', function(e) {
  if (!navigator.onLine) {
    const form = e.detail.elt;
    const url  = e.detail.requestConfig.path;

    const offlineEndpoints = ['/mortality/', '/log/', '/water/'];
    const isOfflineCapable = offlineEndpoints.some(ep => url.includes(ep));

    if (isOfflineCapable && e.detail.requestConfig.verb === 'post') {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form));
      const type = url.includes('mortality') ? 'mortality'
                 : url.includes('eggs')      ? 'eggs'
                 : url.includes('feed')      ? 'feed'
                 : 'water';

      offlineQueue().saveToQueue(type, url, data, data.csrfmiddlewaretoken);

      window.dispatchEvent(new CustomEvent('show-toast', {
        detail: { message: 'Saved offline. Will sync when connected.', type: 'warning' },
      }));
    }
  }
});
