// Adapts window.installerAPI to Tauri v2 invoke/listen.
// Must be loaded BEFORE installer.js so the shape exists when installer.js references it.
(function () {
  'use strict';

  if (!window.__TAURI__ || !window.__TAURI__.core || !window.__TAURI__.event) {
    console.error('[tauri-bridge] Tauri globals missing. withGlobalTauri must be true.');
    return;
  }

  const { invoke } = window.__TAURI__.core;
  const { listen } = window.__TAURI__.event;

  const progressListeners = new Set();
  let unlistenFn = null;

  listen('installer://progress', (event) => {
    for (const cb of progressListeners) {
      try { cb(event.payload); }
      catch (err) { console.error('[tauri-bridge] progress listener threw', err); }
    }
  })
    .then((unlisten) => { unlistenFn = unlisten; })
    .catch((err) => { console.error('[tauri-bridge] listen(installer://progress) failed', err); });

  window.installerAPI = {
    // Pass explicit consent bool so the Rust backend can re-verify it
    // (defense-in-depth against a compromised WebView / crafted IPC).
    startInstall: (consent) => invoke('start_install', { consent: !!consent }),
    cancelInstall: () => invoke('cancel_install'),
    launchApp: () => invoke('launch_app'),
    detectExisting: () => invoke('detect_existing'),
    onProgress: (cb) => {
      progressListeners.add(cb);
      return () => progressListeners.delete(cb);
    },
  };
})();
