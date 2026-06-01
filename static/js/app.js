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
