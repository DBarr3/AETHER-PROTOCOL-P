const root = document.documentElement

const kicker = document.querySelector('[data-kicker]')
const stepCount = document.querySelector('[data-step-count]')
const title = document.querySelector('[data-title]')
const body = document.querySelector('[data-body]')
const sceneBadge = document.querySelector('[data-scene-badge]')
const coreTag = document.querySelector('[data-core-tag]')
const coreTitle = document.querySelector('[data-core-title]')
const coreBody = document.querySelector('[data-core-body]')
const consentRow = document.querySelector('[data-consent-row]')
const consentCheckbox = document.getElementById('consentCheckbox')
const progressLabel = document.querySelector('[data-progress-label]')
const progressValue = document.querySelector('[data-progress-value]')
const progressFill = document.querySelector('[data-progress-fill]')
const progressDetail = document.querySelector('[data-progress-detail]')
const progressSpeed = document.querySelector('[data-progress-speed]')
const primaryButton = document.getElementById('primaryButton')
const backButton = document.getElementById('backButton')
const cancelButton = document.getElementById('cancelButton')
const cards = [...document.querySelectorAll('.info-card')]

let page = 'welcome'
let loop = 0
let progress = 0
let floatLoop = null
let progressLoop = null
let lastExternalProgressAt = 0

const pages = {
  welcome: {
    kicker: 'Welcome',
    count: 'Page 1 of 4',
    title: 'Your agents. Your vaults. Your proof.',
    body: 'AetherCloud brings agents, vaults, automation, and cryptographic proof into one desktop control surface.',
    status: 'Ready',
    focus: 'Trust first',
    badge: 'Trusted setup',
    coreTag: 'secure session',
    coreTitle: 'One command center. Agents, vaults, proof.',
    coreBody: 'Every file gets an ownership path, every agent shows its work, and every transfer can surface a cryptographic receipt.',
    cards: [
      { title: 'Your agents', body: 'Bring agent teams into one workspace.' }
    ],
    progressLabel: 'Ready to begin',
    progressDetail: 'Page 1 of 4',
    progressSpeed: 'Waiting for next step',
    progress: 0,
    primary: 'Next',
    showConsent: false,
    showBack: false,
    disablePrimary: false
  },
  setup: {
    kicker: 'Install',
    count: 'Page 2 of 4',
    title: 'One checkbox. One clear install.',
    body: 'Accept the license, choose whether to launch on finish, and we handle the rest — no extra screens, no scrolling to find the action.',
    status: 'Awaiting consent',
    focus: 'Low friction',
    badge: 'Install ready',
    coreTag: 'guided setup',
    coreTitle: 'Sleek, professional, retro-future.',
    coreBody: 'A short setup page so the product experience starts the moment the download begins, not three screens in.',
    cards: [
      { title: 'Your vaults', body: 'Move files with ownership and control.' }
    ],
    progressLabel: 'Setup',
    progressDetail: 'Page 2 of 4',
    progressSpeed: 'Consent required',
    progress: 18,
    primary: 'Download & install',
    showConsent: true,
    showBack: true,
    disablePrimary: true
  },
  download: {
    kicker: 'Downloading',
    count: 'Page 3 of 4',
    title: 'MCP agents that coordinate real work.',
    body: 'Staging AetherForge, AetherBrowser, the MCP tool registry, and cryptographic modules. One step ahead of you, quietly verifying every byte.',
    status: 'Downloading',
    focus: 'Visible progress',
    badge: 'Orchestration active',
    coreTag: 'live install',
    coreTitle: 'AetherForge · AetherBrowser · MCP tools',
    coreBody: 'Agent teams, browser automation, and vault sync — staging together, ready to launch in sync.',
    cards: [
      { title: 'AetherForge', body: 'Build and automate from one surface.' },
      { title: 'AetherBrowser', body: 'Browse and route work into your system.' }
    ],
    progressLabel: 'Downloading AetherCloud',
    progressDetail: 'Page 3 of 4',
    progressSpeed: 'Connecting to package stream',
    progress: 34,
    primary: 'Installing…',
    showConsent: false,
    showBack: false,
    disablePrimary: true
  },
  final: {
    kicker: 'Ready',
    count: 'Page 4 of 4',
    title: 'SHA-256 verified. Ready to launch.',
    body: 'Every module was hash-checked, every agent module is staged, and the secure session is primed. One click and you are inside.',
    status: 'Ready to launch',
    focus: 'Confident finish',
    badge: 'Proof locked in',
    coreTag: 'verified session',
    coreTitle: 'Integrity first. Control always.',
    coreBody: 'Launch into a system where files stay attributable, agents stay visible, and automation feels premium.',
    cards: [
      { title: 'Your proof', body: 'SHA-256 trust, shown clearly.' },
      { title: 'Launch ready', body: 'Open AetherCloud immediately.' }
    ],
    progressLabel: 'AetherCloud is ready',
    progressDetail: 'Page 4 of 4',
    progressSpeed: 'Verification complete',
    progress: 100,
    primary: 'Launch AetherCloud',
    showConsent: false,
    showBack: false,
    disablePrimary: false
  }
}

function renderCards(items) {
  cards.forEach((card, i) => {
    const item = items[i]
    if (!item) {
      card.classList.remove('is-visible')
      return
    }
    card.classList.add('is-visible')
    card.querySelector('h2').textContent = item.title
    card.querySelector('p').textContent = item.body
  })
}

function renderProgress(value, label, detail, speed) {
  progress = value
  progressFill.style.width = `${value}%`
  progressValue.textContent = `${Math.round(value)}%`
  progressLabel.textContent = label
  progressDetail.textContent = detail
  progressSpeed.textContent = speed
}

function setPage(nextPage) {
  page = nextPage
  root.dataset.page = nextPage
  const cfg = pages[nextPage]
  kicker.textContent = cfg.kicker
  stepCount.textContent = cfg.count
  title.textContent = cfg.title
  body.textContent = cfg.body
  sceneBadge.textContent = cfg.badge
  coreTag.textContent = cfg.coreTag
  coreTitle.textContent = cfg.coreTitle
  coreBody.textContent = cfg.coreBody
  renderCards(cfg.cards)
  renderProgress(cfg.progress, cfg.progressLabel, cfg.progressDetail, cfg.progressSpeed)
  primaryButton.textContent = cfg.primary
  consentRow.hidden = !cfg.showConsent
  backButton.hidden = !cfg.showBack
  cancelButton.textContent = nextPage === 'download' ? 'Run in background' : 'Cancel'
  primaryButton.disabled = cfg.disablePrimary

  if (nextPage === 'welcome' || nextPage === 'final') startFloatLoop()
  else stopFloatLoop()

  if (nextPage === 'download') startProgressLoop()
  else stopProgressLoop()
}

function startFloatLoop() {
  stopFloatLoop()
  floatLoop = setInterval(() => {
    loop = loop === 0 ? 1 : 0
    root.dataset.loop = String(loop)
  }, 2400)
}

function stopFloatLoop() {
  clearInterval(floatLoop)
  root.dataset.loop = '0'
}

function startProgressLoop() {
  // No fake progress — real progress drives UI via installerAPI.onProgress.
}

function stopProgressLoop() {
  clearInterval(progressLoop)
}

function nextPage() {
  if (page === 'welcome') {
    setPage('setup')
  } else if (page === 'setup' && consentCheckbox.checked) {
    setPage('download')
    // Pass consent bool explicitly — backend re-verifies (defense in depth).
    const started = window.installerAPI?.startInstall?.(consentCheckbox.checked)
    if (started && typeof started.catch === 'function') {
      started.catch((err) => {
        console.error('[installer] startInstall rejected', err)
        renderProgress(0, 'Installation failed', String(err), 'See error details')
      })
    } else {
      console.error('[installer] installerAPI.startInstall unavailable — Tauri bridge not loaded')
      renderProgress(0, 'Installation unavailable', 'Tauri bridge not loaded', 'Please reinstall')
    }
  } else if (page === 'final' && window.installerAPI?.launchApp) {
    window.installerAPI.launchApp()
  }
}

function prevPage() {
  if (page === 'setup') setPage('welcome')
}

primaryButton.addEventListener('click', nextPage)
backButton.addEventListener('click', prevPage)
cancelButton.addEventListener('click', () => {
  if (window.installerAPI?.cancelInstall) window.installerAPI.cancelInstall()
})

consentCheckbox.addEventListener('change', () => {
  if (page === 'setup') {
    primaryButton.disabled = !consentCheckbox.checked
    progressSpeed.textContent = consentCheckbox.checked ? 'Ready to install' : 'Consent required'
  }
})

window.installerAPI = window.installerAPI || {}
if (typeof window.installerAPI.onProgress === 'function') {
  window.installerAPI.onProgress((payload) => {
    lastExternalProgressAt = Date.now()
    // Backend state names (installer.rs ProgressEvent.state):
    // fetching_manifest, verifying_manifest, downloading_payload,
    // verifying_payload, installing, done, error, cancelled.
    if (payload.state === 'cancelled') {
      renderProgress(0, payload.label || 'Installation cancelled', payload.detail || 'You can close this window', payload.speed || '')
      return
    }
    if (payload.state === 'error') {
      renderProgress(0, payload.label || 'Installation failed', payload.error || payload.detail || 'See error details', payload.speed || '')
      return
    }
    if (payload.state === 'downloading_payload' && page !== 'download') setPage('download')
    if (payload.percent !== undefined && page === 'download') {
      renderProgress(Number(payload.percent), payload.label || 'Downloading AetherCloud', payload.detail || 'Page 3 of 4', payload.speed || 'Processing install tasks')
    }
    if (payload.state === 'done' || payload.percent >= 100) {
      setPage('final')
    }
  })
}

setPage('welcome')
