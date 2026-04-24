// POST-INSTALL events only. Wizard funnel is instrumented in desktop-installer/src-tauri/. See issue #50.
const root = document.documentElement

const kicker = document.querySelector('[data-kicker]')
const stepCount = document.querySelector('[data-step-count]')
const title = document.querySelector('[data-title]')
const body = document.querySelector('[data-body]')
const telemetry = document.querySelector('[data-telemetry]')
const statusEl = document.querySelector('[data-status]')
const focusEl = document.querySelector('[data-focus]')
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
    telemetry: 'welcome // trust // control // start install',
    status: 'Ready',
    focus: 'Trust first',
    badge: 'Trusted setup',
    coreTag: 'secure session',
    coreTitle: 'Why keep going?',
    coreBody: 'Because this app feels controlled, trusted, and useful before it even opens.',
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
    title: 'Simple setup. Clear next step.',
    body: 'Keep this page light: one short value statement, one checkbox, one clear install action.',
    telemetry: 'license // launch preference // install path',
    status: 'Awaiting consent',
    focus: 'Low friction',
    badge: 'Install ready',
    coreTag: 'guided setup',
    coreTitle: 'A desktop installer should feel obvious.',
    coreBody: 'No scrolling to find the main action. Keep the install button anchored and visible.',
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
    title: 'Installing tools, vaults, and automation.',
    body: 'This page should reassure the user. Show real progress. Keep the words short. Let the installer feel active, not loud.',
    telemetry: 'download // unpack // stage mcp tools // sync automation',
    status: 'Downloading',
    focus: 'Visible progress',
    badge: 'Orchestration active',
    coreTag: 'live install',
    coreTitle: 'AetherForge + AetherBrowser + MCP tools',
    coreBody: 'Automate agent teams and prepare the app without overwhelming the user with too much copy.',
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
    title: 'Verified. Ready to launch.',
    body: 'End on confidence. Proof is complete, the app is ready, and the final scene should feel calm and premium.',
    telemetry: 'sha256 // verification passed // launch handoff',
    status: 'Ready to launch',
    focus: 'Confident finish',
    badge: 'Proof locked in',
    coreTag: 'verified session',
    coreTitle: 'Agents that learn and improve',
    coreBody: 'Launch into a system that adapts to the user and keeps agent work coordinated.',
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
  telemetry.textContent = cfg.telemetry
  statusEl.textContent = cfg.status
  focusEl.textContent = cfg.focus
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
  stopProgressLoop()
  progressLoop = setInterval(() => {
    if (Date.now() - lastExternalProgressAt < 2400) return
    if (page !== 'download') return
    const next = Math.min(progress + Math.random() * 8 + 3, 94)
    const speed = next < 52 ? 'Receiving packages' : next < 78 ? 'Staging tools' : 'Running verification prep'
    renderProgress(next, 'Downloading AetherCloud', 'Page 3 of 4', speed)
    if (next >= 94) {
      stopProgressLoop()
      setPage('final')
    }
  }, 1600)
}

function stopProgressLoop() {
  clearInterval(progressLoop)
}

function nextPage() {
  if (page === 'welcome') setPage('setup')
  else if (page === 'setup' && consentCheckbox.checked) setPage('download')
  else if (page === 'final' && window.installerAPI?.launchApp) window.installerAPI.launchApp()
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
    if (payload.state === 'download' && page !== 'download') setPage('download')
    if (payload.percent !== undefined && page === 'download') {
      renderProgress(Number(payload.percent), payload.label || 'Downloading AetherCloud', payload.detail || 'Page 3 of 4', payload.speed || 'Processing install tasks')
    }
    if (payload.percent >= 100 || payload.state === 'final') {
      setPage('final')
    }
  })
}

setPage('welcome')
