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

  if (window.installerAPI?.startInstall) {
    window.installerAPI.startInstall(consentCheckbox.checked);
  } else {
    // Fallback demo progress for standalone preview
    demoProgress();
  }
});

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
      renderProgress(progressFill.style.width ? parseFloat(progressFill.style.width) : 0, payload.label || 'Install failed');
      installButton.textContent = 'Retry';
      installButton.disabled = false;
      installing = false;
      startTaglineLoop();
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
