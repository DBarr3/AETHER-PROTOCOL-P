// AetherCloud Installer — minimal controller
// Trust-first order: audit + IP claims lead. Technical users install on
// trust; marketing capability closes after trust is established.
const TAGLINES = [
  'Every view is logged and audited.',
  'AetherBrowser automates any task on the web — your IP never reaches the endpoint.',
  'Stash a file in the vault. Work on it later.',
  'Create your agents. Customize them. They learn from you.',
  'Orchestrate agent teams. Do your business.',
  'New MCPs and agent tools, shipped every day.'
];

const taglineEl = document.getElementById('tagline');
const dotsEl = document.getElementById('taglineDots');
const consentCheckbox = document.getElementById('consentCheckbox');
const installButton = document.getElementById('installButton');
const cancelButton = document.getElementById('cancelButton');
const progressShell = document.getElementById('progressShell');
const progressFill = document.getElementById('progressFill');
const progressLabel = document.getElementById('progressLabel');
const progressValue = document.getElementById('progressValue');

let taglineIndex = 0;
let taglineTimer = null;
let installing = false;
// If the backend doesn't emit a single progress event within this many ms
// after the install click, surface a loud error instead of sitting at 0%.
const BACKEND_START_WATCHDOG_MS = 10_000;
let backendWatchdog = null;
let lastProgressAt = 0;
// Log file path hint shown in error messages so users can actually find it.
const LOG_HINT = '%LOCALAPPDATA%\\AetherCloud-Setup\\install.log';

// Build dots
TAGLINES.forEach((_, i) => {
  const dot = document.createElement('span');
  if (i === 0) dot.classList.add('is-active');
  dotsEl.appendChild(dot);
});
const dotNodes = [...dotsEl.children];

function showTagline(i) {
  taglineEl.classList.add('is-fading');
  setTimeout(() => {
    taglineEl.textContent = TAGLINES[i];
    dotNodes.forEach((d, idx) => d.classList.toggle('is-active', idx === i));
    taglineEl.classList.remove('is-fading');
  }, 340);
}

function startTaglineLoop() {
  stopTaglineLoop();
  taglineTimer = setInterval(() => {
    taglineIndex = (taglineIndex + 1) % TAGLINES.length;
    showTagline(taglineIndex);
  }, 4800);
}

function stopTaglineLoop() {
  if (taglineTimer) { clearInterval(taglineTimer); taglineTimer = null; }
}

// Consent gate
consentCheckbox.addEventListener('change', () => {
  installButton.disabled = !consentCheckbox.checked;
});

// Install
installButton.addEventListener('click', () => {
  if (!consentCheckbox.checked || installing) return;
  installing = true;
  installButton.disabled = true;
  installButton.textContent = 'Installing…';
  consentCheckbox.disabled = true;
  progressShell.hidden = false;
  // Freeze the rotating tagline during install — three simultaneous
  // motions (tagline / progress bar / orbit) is visual noise at the
  // moment the user wants calm. Resume on error or cancel.
  stopTaglineLoop();
  renderProgress(0, 'Starting install…');
  lastProgressAt = Date.now();

  // Watchdog: if no progress event arrives from the backend within
  // BACKEND_START_WATCHDOG_MS, show a loud error pointing at the log.
  // This is the fix for the "hang at 0%" class of bugs — backend is
  // silent (TLS stalled, AV sandbox holding the process, etc.) but the
  // UI used to sit forever. Now it fails loud.
  if (backendWatchdog) clearTimeout(backendWatchdog);
  backendWatchdog = setTimeout(() => {
    if (!installing) return; // install finished/cancelled before watchdog
    if (Date.now() - lastProgressAt < BACKEND_START_WATCHDOG_MS - 500) return; // a tick came in
    console.error('[installer] watchdog: no progress event within 10s');
    surfaceError(
      'Backend not responding',
      `The install backend didn't send a progress event in 10 seconds. Check the log at ${LOG_HINT} and send it to support. Your install has NOT been modified.`
    );
  }, BACKEND_START_WATCHDOG_MS);

  if (window.installerAPI?.startInstall) {
    // Keep a promise ref so we can catch IPC-level rejection (command not
    // registered, serialization fail, backend panic before first emit).
    let started;
    try {
      started = window.installerAPI.startInstall(consentCheckbox.checked);
    } catch (syncErr) {
      console.error('[installer] startInstall threw synchronously', syncErr);
      surfaceError('Installation failed to start', String(syncErr) + '\n\nSee ' + LOG_HINT);
      return;
    }
    if (started && typeof started.catch === 'function') {
      started.catch((err) => {
        console.error('[installer] startInstall IPC rejected', err);
        // If an onProgress error event already fired, don't double-render.
        // Errors from the Err(...) match arm in commands.rs always emit first.
        if (!installing) return;
        surfaceError('Installation failed to start', String(err) + '\n\nSee ' + LOG_HINT);
      });
    }
  } else {
    // Fallback demo progress for standalone preview (no Tauri bridge).
    if (backendWatchdog) { clearTimeout(backendWatchdog); backendWatchdog = null; }
    demoProgress();
  }
});

/**
 * Put the wizard into a visible error state: progress label becomes the
 * message, install button becomes Retry, consent is re-enabled so the user
 * can try again. Shared by backend error events, IPC rejections, and the
 * frontend watchdog.
 */
function surfaceError(label, detail) {
  installing = false;
  renderProgress(0, label);
  progressLabel.textContent = label;
  // Keep the detail text somewhere visible — append under the label.
  // (Avoids introducing a new DOM node; fits the minimalist layout.)
  progressLabel.title = detail;
  installButton.textContent = 'Retry';
  installButton.disabled = false;
  consentCheckbox.disabled = false;
  if (backendWatchdog) { clearTimeout(backendWatchdog); backendWatchdog = null; }
  startTaglineLoop();
}

cancelButton.addEventListener('click', () => {
  if (window.installerAPI?.cancelInstall) {
    window.installerAPI.cancelInstall();
  } else {
    window.close();
  }
});

// Progress rendering
function renderProgress(pct, label) {
  const v = Math.max(0, Math.min(100, pct));
  const rounded = Math.round(v);
  progressFill.style.width = v + '%';
  progressValue.textContent = rounded + '%';
  if (label) progressLabel.textContent = label;
  // ARIA so screen readers announce progress updates
  progressShell.setAttribute('role', 'progressbar');
  progressShell.setAttribute('aria-valuenow', String(rounded));
  progressShell.setAttribute('aria-valuemin', '0');
  progressShell.setAttribute('aria-valuemax', '100');
  progressShell.setAttribute('aria-valuetext', label ? `${label} ${rounded}%` : `${rounded}%`);
}

// Backend bridge
window.installerAPI = window.installerAPI || {};
if (typeof window.installerAPI.onProgress === 'function') {
  window.installerAPI.onProgress((payload) => {
    if (!payload) return;
    // Any event from the backend clears the "hang at 0%" watchdog.
    lastProgressAt = Date.now();
    if (backendWatchdog) { clearTimeout(backendWatchdog); backendWatchdog = null; }

    if (payload.percent !== undefined) {
      renderProgress(Number(payload.percent), payload.label);
    }
    if (payload.state === 'done' || payload.percent >= 100) {
      renderProgress(100, 'Install complete. Launching…');
      installButton.textContent = 'Launching…';
      // Give the user ~800ms to see "Launching…" before the wizard closes.
      setTimeout(() => {
        if (window.installerAPI?.launchApp) window.installerAPI.launchApp();
      }, 800);
    }
    if (payload.state === 'cancelled') {
      renderProgress(0, payload.label || 'Install cancelled');
      installButton.textContent = 'Install AetherCloud';
      consentCheckbox.disabled = false;
      installButton.disabled = !consentCheckbox.checked;
      installing = false;
      progressShell.hidden = true;
      startTaglineLoop();
    }
    if (payload.state === 'error') {
      // Prefer the specific backend error string (payload.error) over the
      // generic "Installation failed" label. Falls back to label if the
      // backend didn't populate an error message.
      const message = payload.error || payload.label || 'Install failed';
      const detail = payload.detail
        ? `${payload.detail}\n\nLog: ${LOG_HINT}`
        : `Log: ${LOG_HINT}`;
      surfaceError(message, detail);
    }
  });
}

// Standalone demo mode (when no backend bridge)
function demoProgress() {
  let p = 0;
  const phases = [
    { at: 20, label: 'Downloading payload…' },
    { at: 55, label: 'Verifying signature…' },
    { at: 80, label: 'Unpacking tools…' },
    { at: 100, label: 'Install complete.' }
  ];
  const tick = setInterval(() => {
    p = Math.min(p + Math.random() * 6 + 2, 100);
    const phase = phases.find(x => p < x.at) || phases[phases.length - 1];
    renderProgress(p, phase.label);
    if (p >= 100) {
      clearInterval(tick);
      installButton.textContent = 'Launched';
    }
  }, 420);
}

// Boot
startTaglineLoop();
