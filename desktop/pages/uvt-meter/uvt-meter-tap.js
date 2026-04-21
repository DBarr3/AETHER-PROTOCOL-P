/* ═══════════════════════════════════════════════════════════════
   AetherCloud · UVT Meter response-tap

   Wraps the existing `authFetch` so every successful /agent/run
   response feeds the RouterResponse body to the UVT Meter, and any
   402/429 guard-deny surfaces in the UVT panel.

   Load order (dashboard.html):
     <script src="./uvt-meter/uvt-meter.js"></script>
     ...existing page scripts that define authFetch()...
     <script src="./uvt-meter/uvt-meter-tap.js"></script>

   Idempotent, fail-closed — original authFetch behaviour is 100%
   preserved if anything here throws.
   ═══════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  // Routes whose response bodies are RouterResponse envelopes.
  // Expand as more UVT-metered endpoints are added.
  const UVT_ROUTES = [
    '/agent/run',
  ];

  function urlFor(args) {
    const u = args && args[0];
    if (typeof u === 'string') return u;
    try { return (u && (u.url || String(u))) || ''; } catch { return ''; }
  }

  function isUvtRoute(url) {
    return UVT_ROUTES.some(r => url.includes(r));
  }

  function wrap(fnName, target) {
    if (!target || typeof target[fnName] !== 'function') return;
    if (target[fnName].__uvtTapped) return;

    const original = target[fnName];
    const wrapped = async function (...args) {
      const resp = await original.apply(this, args);
      try {
        const url = urlFor(args);
        if (!isUvtRoute(url) || !window.UvtMeter) return resp;

        // Clone before reading body so downstream await resp.json() still works
        let parsed = null;
        try {
          const clone = resp.clone();
          const text = await clone.text();
          parsed = text ? JSON.parse(text) : null;
        } catch (_) { /* not JSON — ignore */ }

        if (resp.ok && parsed) {
          window.UvtMeter.ingestRouterResponse(parsed);
        } else if (!resp.ok && parsed) {
          // FastAPI error envelope: { detail: { error, upgrade_to, ... } }
          window.UvtMeter.ingestGuardDeny(parsed);
        }
      } catch (e) {
        console.debug('[UvtMeter/tap] ingest failed:', e && e.message);
      }
      return resp;
    };
    wrapped.__uvtTapped = true;
    target[fnName] = wrapped;
  }

  function install() {
    if (typeof window.authFetch === 'function') {
      wrap('authFetch', window);
      console.info('[UvtMeter/tap] authFetch wrapped');
      return true;
    }
    return false;
  }

  if (!install()) {
    let tries = 0;
    const iv = setInterval(() => {
      if (install() || ++tries > 40) clearInterval(iv);
    }, 250);
  }
})();
