/* ═══════════════════════════════════════════════════════════════
   AetherCloud · UVT Meter · v3 (tiny, glanceable)

   Same backend contract — GET /account/usage + /agent/run.
   Popover is a 152px tile:

     [ ▓  1.58M  ┃┃┃ ]     tube + number + 3 mini bars
     [    UVT         ]
     [ ● healthy  more ]

   Tap "more" → slides open tiny details (daily/concurrency/reset)
   + single action button (upgrade or overage). Advanced state
   (last-call, flags) lives only in the expanded view.

   Public API unchanged from v1:
     window.UvtMeter.mount(host, { apiBase, getToken })
     window.UvtMeter.refresh()
     window.UvtMeter.ingestRouterResponse(body)
     window.UvtMeter.ingestGuardDeny(err)
     window.UvtMeter.setOverage(enabled, capCents)
     window.UvtMeter.open() / close()
   ═══════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  const LS_SNAP = 'uvtmeter.snapshot.v1';
  const LS_LAST = 'uvtmeter.lastcall.v1';
  const REFRESH_COOLDOWN_MS = 10_000;

  const state = {
    cfg: { apiBase: '', getToken: null },
    snapshot: safeParse(lsGet(LS_SNAP)),
    lastCall: safeParse(lsGet(LS_LAST)),
    lastDeny: null,
    mounted: false,
    els: null,
    isOpen: false,
    isExpanded: false,
    lastFetchAt: 0,
    pending: null,
  };

  function safeParse(raw) { try { return JSON.parse(raw); } catch { return null; } }
  function lsGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch {} }
  function n(x) { const v = typeof x === 'number' ? x : parseFloat(x); return Number.isFinite(v) ? v : 0; }
  function escapeHTML(s) {
    return String(s ?? '').replace(/[&<>"']/g, (ch) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));
  }

  // ────────────────────────────────────────────────
  // Backend calls
  // ────────────────────────────────────────────────
  async function fetchUsage() {
    const { apiBase, getToken } = state.cfg;
    if (!apiBase) return null;
    const token = typeof getToken === 'function' ? await getToken() : null;
    if (!token) return null;
    const now = Date.now();
    if (now - state.lastFetchAt < REFRESH_COOLDOWN_MS && state.snapshot) return state.snapshot;
    if (state.pending) return state.pending;
    state.pending = (async () => {
      try {
        const resp = await fetch(`${apiBase}/account/usage`, { headers: { Authorization: `Bearer ${token}` } });
        if (!resp.ok) return null;
        const body = await resp.json();
        state.snapshot = body;
        state.lastFetchAt = Date.now();
        lsSet(LS_SNAP, JSON.stringify(body));
        state.lastDeny = null;
        render();
        return body;
      } catch (e) {
        console.debug('[UvtMeter] fetch failed:', e?.message);
        return null;
      } finally { state.pending = null; }
    })();
    return state.pending;
  }

  function ingestRouterResponse(body) {
    if (!body || typeof body !== 'object') return;
    // The buried-fallback field was removed from the backend response in
    // PR 1 v5 (see diagrams/docs_router_architecture.md § "Philosophy —
    // honest limits"). The UI must NOT re-read it — resurrecting the
    // field here silently re-enables the UX the arch doc forbids.
    state.lastCall = {
      model: body.orchestrator_model || body.model || null,
      load: body.load || body.qopc_load || null,
      confidence: typeof body.confidence === 'number' ? body.confidence : null,
      total_uvt: n(body.total_uvt),
      classifier_uvt: n(body.classifier_uvt),
      reclassified: !!body.reclassified,
      at: Date.now(),
    };
    lsSet(LS_LAST, JSON.stringify(state.lastCall));
    state.lastDeny = null;
    fetchUsage();
    render();
  }

  function ingestGuardDeny(err) {
    if (!err) return;
    const d = err.detail || err;
    state.lastDeny = {
      error: d.error || 'unknown',
      upgrade_to: d.upgrade_to || null,
      daily_cap: d.daily_uvt_cap,
      monthly_cap: d.monthly_uvt_cap,
      concurrency_cap: d.concurrency_cap,
    };
    render();
  }

  async function setOverage(enabled, capUsdCents) {
    const { apiBase, getToken } = state.cfg;
    if (!apiBase) return { ok: false, error: 'no_api_base' };
    const token = typeof getToken === 'function' ? await getToken() : null;
    if (!token) return { ok: false, error: 'no_token' };
    try {
      const resp = await fetch(`${apiBase}/account/overage`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !!enabled, cap_usd_cents: capUsdCents ?? null }),
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) return { ok: false, status: resp.status, ...body };
      state.snapshot = { ...state.snapshot, ...body };
      lsSet(LS_SNAP, JSON.stringify(state.snapshot));
      render();
      return { ok: true };
    } catch (e) { return { ok: false, error: e.message }; }
  }

  // ────────────────────────────────────────────────
  // Formatting + severity
  // ────────────────────────────────────────────────
  function fmtUVT(v) {
    if (v == null || !Number.isFinite(v)) return '—';
    if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return String(Math.round(v));
  }
  function pct(used, cap) {
    if (!cap || !Number.isFinite(cap) || cap <= 0) return 0;
    return Math.min(100, Math.max(0, (used / cap) * 100));
  }
  function severityFromPct(p) {
    if (p >= 90) return 'err';
    if (p >= 70) return 'warn';
    return 'ok';
  }
  function fmtDays(d) {
    if (d == null) return '—';
    if (d <= 0) return 'today';
    if (d === 1) return '1d';
    return `${d}d`;
  }
  function modelShort(m) {
    if (!m) return '—';
    const s = String(m).toLowerCase();
    if (s.includes('opus'))   return 'Opus';
    if (s.includes('sonnet')) return 'Sonnet';
    if (s.includes('haiku'))  return 'Haiku';
    return m;
  }
  function modelClass(m) {
    if (!m) return '';
    const s = String(m).toLowerCase();
    if (s.includes('opus')) return 'opus';
    if (s.includes('sonnet')) return 'sonnet';
    if (s.includes('haiku')) return 'haiku';
    return '';
  }
  function tierClass(t) {
    return ['free','solo','pro','team'].includes(String(t)) ? String(t) : '';
  }
  function worstPct() {
    const s = state.snapshot;
    if (!s) return 0;
    return Math.max(pct(s.monthly_uvt_used, s.monthly_uvt_cap), pct(s.daily_uvt_used, s.daily_uvt_cap));
  }
  function concPct() {
    const s = state.snapshot;
    if (!s) return 0;
    return pct(s.concurrency_used, s.concurrency_cap);
  }
  function overallSeverity() {
    if (state.lastDeny) {
      if (state.lastDeny.error === 'concurrency') return 'warn';
      return 'err';
    }
    if (state.snapshot?.overage_in_effect) return 'overage';
    return severityFromPct(worstPct());
  }

  // ────────────────────────────────────────────────
  // Markup
  // ────────────────────────────────────────────────
  function iconSVG() {
    return `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3 Q6 10 6 14 a6 6 0 0 0 12 0 Q18 10 12 3 Z"/>
      </svg>`;
  }

  function bannerFor() {
    const d = state.lastDeny;
    const s = state.snapshot;
    if (d) {
      if (d.error === 'monthly_quota') return {
        cls: 'err',
        text: `Quota spent. ${d.upgrade_to ? `Upgrade or` : ''} enable overage.`.trim(),
      };
      if (d.error === 'daily_cap') return {
        cls: 'warn', text: `Daily cap hit · resets 00:00 UTC.`
      };
      if (d.error === 'concurrency') return {
        cls: 'warn', text: `All ${d.concurrency_cap} slots busy.`
      };
    }
    if (s?.overage_in_effect) return { cls: 'overage', text: `Overage mode · billed at cycle end.` };
    return null;
  }

  function suggestUpgrade(s) {
    if (!s) return null;
    if (worstPct() < 80) return null;
    const t = s.tier;
    if (t === 'free') return 'solo';
    if (t === 'solo') return 'pro';
    if (t === 'pro')  return 'team';
    return null;
  }

  // ────────────────────────────────────────────────
  // Mount
  // ────────────────────────────────────────────────
  function mount(host, cfg) {
    if (!host) { console.warn('[UvtMeter] no host'); return null; }
    if (state.mounted) return publicApi;
    state.cfg = Object.assign({ apiBase: '', getToken: null }, cfg || {});

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'uvt-trigger';
    trigger.title = 'UVT usage';
    trigger.setAttribute('aria-label', 'Open UVT usage');
    trigger.dataset.severity = 'ok';
    trigger.innerHTML = `<span class="uvt-ring" style="--pct:0"></span>${iconSVG()}`;
    host.appendChild(trigger);

    const pop = document.createElement('div');
    pop.className = 'uvt-popover';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'UVT usage panel');
    const inputBar = host.closest('.input-bar') || host.parentElement;
    (inputBar?.parentElement || document.body).appendChild(pop);

    state.mounted = true;
    state.els = { host, trigger, pop };

    trigger.addEventListener('click', () => toggle());
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state.isOpen) toggle(false);
    });

    render();
    fetchUsage();
    return publicApi;
  }

  function toggle(force) {
    const { trigger, pop } = state.els || {};
    if (!trigger || !pop) return;
    const next = typeof force === 'boolean' ? force : !state.isOpen;
    if (next === state.isOpen) return;
    state.isOpen = next;
    trigger.classList.toggle('open', next);
    pop.classList.toggle('open', next);
    if (next) {
      fetchUsage();
      render();
      setTimeout(() => document.addEventListener('mousedown', outsideClick), 0);
    } else {
      document.removeEventListener('mousedown', outsideClick);
    }
  }
  function outsideClick(e) {
    const { trigger, pop } = state.els || {};
    if (!pop || !trigger) return;
    if (!pop.contains(e.target) && !trigger.contains(e.target)) toggle(false);
  }

  // ────────────────────────────────────────────────
  // Render
  // ────────────────────────────────────────────────
  function render() {
    const { trigger, pop } = state.els || {};
    if (!trigger) return;

    const sev = overallSeverity();
    const worst = worstPct();
    trigger.dataset.severity = sev;
    trigger.querySelector('.uvt-ring').style.setProperty('--pct', Math.round(worst));

    if (!pop || !state.isOpen) return;

    const s = state.snapshot;
    const hasData = s && (Number.isFinite(s.monthly_uvt_cap) || Number.isFinite(s.daily_uvt_cap));

    pop.classList.toggle('expanded', !!state.isExpanded);

    if (!hasData) {
      pop.innerHTML = `
        <div class="uvt-empty">Sign in to see your<br/>token balance.</div>
      `;
      return;
    }

    const remaining = s.monthly_uvt_remaining;
    const statusText =
      sev === 'overage' ? 'overage' :
      sev === 'err'     ? 'low' :
      sev === 'warn'    ? 'heads up' : 'healthy';

    const monthSev = severityFromPct(pct(s.monthly_uvt_used, s.monthly_uvt_cap));
    const daySev   = severityFromPct(pct(s.daily_uvt_used, s.daily_uvt_cap));
    const concP    = concPct();
    const concSev  = concP >= 100 ? 'err' : (concP >= 67 ? 'warn' : 'ok');

    const monthPct = pct(s.monthly_uvt_used, s.monthly_uvt_cap);
    const dayPct   = pct(s.daily_uvt_used, s.daily_uvt_cap);

    const c = state.lastCall;
    const upgrade = state.lastDeny?.upgrade_to || suggestUpgrade(s);

    pop.innerHTML = `
      <div class="uvt-hero">
        <div class="uvt-tube ${sev}">
          <div class="uvt-tube-fill" style="height:${Math.round(100 - monthPct)}%"></div>
        </div>
        <div class="uvt-hero-mid">
          <div class="uvt-big ${sev}">${fmtUVT(remaining)}</div>
          <span class="uvt-unit">tokens left</span>
        </div>
        <div class="uvt-bars">
          <div class="uvt-bar ${monthSev}" data-label="M" title="Monthly">
            <div class="uvt-bar-fill" style="height:${Math.round(100 - monthPct)}%"></div>
          </div>
          <div class="uvt-bar ${daySev}" data-label="D" title="Daily">
            <div class="uvt-bar-fill" style="height:${Math.round(100 - dayPct)}%"></div>
          </div>
          <div class="uvt-bar ${concSev}" data-label="C" title="Concurrent">
            <div class="uvt-bar-fill" style="height:${Math.round(100 - concP)}%"></div>
          </div>
        </div>
      </div>

      <div class="uvt-foot">
        <span class="uvt-foot-status ${sev}">
          <span class="uvt-pulse-dot ${sev}"></span>${statusText}
        </span>
        <button class="uvt-more" id="uvt-more">${state.isExpanded ? 'less' : 'more'}</button>
      </div>

      <div class="uvt-details">
        <div class="uvt-det-row">
          <span>monthly</span>
          <span class="${monthSev === 'ok' ? '' : monthSev}">${fmtUVT(s.monthly_uvt_used)} / ${fmtUVT(s.monthly_uvt_cap)}</span>
        </div>
        <div class="uvt-det-row">
          <span>daily</span>
          <span class="${daySev === 'ok' ? '' : daySev}">${fmtUVT(s.daily_uvt_used)} / ${fmtUVT(s.daily_uvt_cap)}</span>
        </div>
        <div class="uvt-det-row">
          <span>running</span>
          <span class="${concSev === 'ok' ? '' : concSev}">${n(s.concurrency_used)} / ${n(s.concurrency_cap)}</span>
        </div>
        <div class="uvt-det-row">
          <span>resets</span>
          <span>${fmtDays(s.days_until_reset)}</span>
        </div>
        ${s.overage_enabled ? `
          <div class="uvt-det-row">
            <span>overage</span>
            <span class="${s.overage_in_effect ? 'warn' : ''}">$${((s.overage_usd_cents_used || 0)/100).toFixed(2)}</span>
          </div>
        ` : ''}
        ${c ? `
          <div class="uvt-det-row">
            <span>last call</span>
            <span>${escapeHTML(modelShort(c.model))} · ${fmtUVT(c.total_uvt)}</span>
          </div>
        ` : ''}
        ${upgrade
          ? `<button class="uvt-action upgrade" id="uvt-upgrade">Upgrade to ${escapeHTML(upgrade)}</button>`
          : `<button class="uvt-action" id="uvt-overage">${s.overage_enabled ? 'Manage overage' : 'Enable overage'}</button>`
        }
      </div>
    `;

    const moreBtn = pop.querySelector('#uvt-more');
    if (moreBtn) moreBtn.addEventListener('click', () => {
      state.isExpanded = !state.isExpanded;
      render();
    });
    const upBtn = pop.querySelector('#uvt-upgrade');
    if (upBtn) upBtn.addEventListener('click', () => openUpgrade(upgrade));
    const ovBtn = pop.querySelector('#uvt-overage');
    if (ovBtn) ovBtn.addEventListener('click', () => openOverage());
  }

  function openUpgrade(tier) {
    try { if (window.aetherUpgrade?.open) return window.aetherUpgrade.open(tier); } catch {}
    window.location.hash = `#/upgrade?tier=${encodeURIComponent(tier)}`;
  }
  function openOverage() {
    try { if (window.aetherAccount?.openOverage) return window.aetherAccount.openOverage(); } catch {}
    window.location.hash = '#/account/overage';
  }

  const publicApi = {
    mount,
    refresh: () => { state.lastFetchAt = 0; return fetchUsage(); },
    ingestRouterResponse,
    ingestGuardDeny,
    setOverage,
    open:  () => toggle(true),
    close: () => toggle(false),
    _state: state,
  };
  window.UvtMeter = publicApi;
})();
