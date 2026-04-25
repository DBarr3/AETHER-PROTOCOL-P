/* ------------------------------------------------------------------
   AetherCloud Checkout v3 â€” interactive logic
   - Pixel-art agents that loop their default sequence on each card
   - Osmo-style interactive glowing dot field background
   - Cursor halo + AetherCloud wordmark hot-spot follows the cursor
   - Monthly / Annual toggle with smooth price morph
   - subscribe(tier) stub -> wire to Stripe Checkout Session endpoint
   - 3D tilt on hover (disabled on touch / reduced-motion)
   - Keyboard: Enter/Space on focused card triggers subscribe
------------------------------------------------------------------- */

(() => {
  const prefersReduced =
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isTouch = matchMedia('(hover: none)').matches;

  /* ---------- Stripe price-ID map (replace at deploy) ---------- */
  const PRICE_IDS = {
    solo: { monthly: 'price_solo_monthly', annual: 'price_solo_annual' },
    pro:  { monthly: 'price_pro_monthly',  annual: 'price_pro_annual'  },
    team: { monthly: 'price_team_monthly', annual: 'price_team_annual' },
  };

  let currentCycle = 'monthly';

  /* =================================================================
     1) PIXEL AGENT RUNTIME
     Each .agent-canvas reads data-agent + data-sequence from window.__AETHER_AGENTS__
     and renders one looped sprite animation. ~5-10kb of paint cost total.
     ================================================================= */

  const AGENT_DATA = window.__AETHER_AGENTS__ || {};

  function makeAgent(canvas) {
    const key = canvas.dataset.agent;
    const data = AGENT_DATA[key];
    if (!data) {
      console.warn('[agent] unknown', key);
      return null;
    }
    const seqName = canvas.dataset.sequence || data.defaultSequence;
    const seq = data.sequences[seqName] || data.sequences[data.defaultSequence];
    if (!seq) return null;

    const W = data.gridWidth;
    const H = data.gridHeight;
    const colors = data.colors || {};

    // Resolve a color key to hex.  Some agents store hex directly,
    // others use a key like 'G'.  Pass-through if it already looks like a hex.
    const resolve = (c) => (typeof c === 'string' && c[0] === '#') ? c : (colors[c] || '#ffffff');

    // Pre-bake each frame into a tiny offscreen canvas at native pixel size,
    // then we just drawImage scaled â€” keeps redraws cheap.
    const baked = data.frames.map((f) => {
      const oc = document.createElement('canvas');
      oc.width = W;
      oc.height = H;
      const octx = oc.getContext('2d');
      f.pixels.forEach(([x, y, c]) => {
        if (x < 0 || y < 0 || x >= W || y >= H) return;
        octx.fillStyle = resolve(c);
        octx.fillRect(x, y, 1, 1);
      });
      return oc;
    });

    // Size the visible canvas. CSS controls display size; we set the bitmap
    // to a multiple of the grid for crisp pixels at any DPR.
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssH = canvas.clientHeight || 80;
    // Aspect is W/H of the grid
    const cssW = Math.round(cssH * (W / H));
    canvas.style.width = cssW + 'px';
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;

    let step = 0;
    let lastSwitch = 0;
    let raf = 0;
    let visible = true;
    let onScreen = true;

    const draw = (frameIdx) => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(baked[frameIdx], 0, 0, canvas.width, canvas.height);
    };

    // Draw initial frame so it's visible even if rAF is throttled
    draw(seq.frames[0]);

    const tick = (ts) => {
      if (!visible || !onScreen) {
        raf = requestAnimationFrame(tick);
        return;
      }
      const delay = seq.delays[step] || 200;
      if (ts - lastSwitch > delay) {
        lastSwitch = ts;
        step = (step + 1) % seq.frames.length;
        draw(seq.frames[step]);
      }
      raf = requestAnimationFrame(tick);
    };

    if (prefersReduced) {
      // Single static frame is enough
      return { stop: () => {} };
    }

    raf = requestAnimationFrame(tick);

    // Pause when tab is hidden, resume when shown
    document.addEventListener('visibilitychange', () => {
      visible = document.visibilityState === 'visible';
      lastSwitch = performance.now();
    });

    // Pause when scrolled off-screen
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          onScreen = e.isIntersecting;
          if (onScreen) lastSwitch = performance.now();
        });
      }, { rootMargin: '100px' });
      io.observe(canvas);
    }

    return {
      stop: () => cancelAnimationFrame(raf),
      // Swap to a different sequence at runtime
      setSequence(name) {
        const next = data.sequences[name];
        if (!next) return;
        seq.frames = next.frames;
        seq.delays = next.delays;
        step = 0;
        lastSwitch = 0;
        draw(seq.frames[0]);
      },
    };
  }

  // Init all agent canvases and remember controllers per card
  const agentControllers = new Map();
  document.querySelectorAll('.agent-canvas').forEach((c) => {
    const ctrl = makeAgent(c);
    if (ctrl) {
      const card = c.closest('.plan');
      if (card) agentControllers.set(card, { ctrl, canvas: c });
    }
  });

  // On hover, switch the agent into a more active sequence; on leave, back to idle.
  // We pick a smart "active" sequence per agent â€” its non-idle one.
  const ACTIVE_SEQ = {
    green:  'dart',
    silver: 'walk',
    bolt:   'zap',   // already zap on Pro; keep zap on hover
    cloud:  'drift',
  };
  if (!isTouch && !prefersReduced) {
    agentControllers.forEach(({ ctrl, canvas }, card) => {
      const baseSeq = canvas.dataset.sequence || 'idle';
      const activeSeq = ACTIVE_SEQ[canvas.dataset.agent] || baseSeq;
      card.addEventListener('mouseenter', () => ctrl.setSequence(activeSeq));
      card.addEventListener('mouseleave', () => ctrl.setSequence(baseSeq));
    });
  }

  /* =================================================================
     2) GLOWING DOT FIELD BACKGROUND  (Osmo-style)
     A grid of dim dots; the closer to the cursor, the brighter & larger.
     Fully canvas, no DOM nodes per dot.
     ================================================================= */

  const dotsCanvas = document.getElementById('bg-dots');
  if (dotsCanvas && !prefersReduced) {
    const ctx = dotsCanvas.getContext('2d');

    let W = 0, H = 0, dpr = 1;
    let cols = 0, rows = 0;
    let mouseX = -9999, mouseY = -9999;
    let targetX = -9999, targetY = -9999;
    let hasCursor = false;

    const SPACING = 26;   // distance between dots (CSS px)
    const RADIUS  = 1.4;  // base dot radius (CSS px)
    const INFLUENCE = 180; // glow radius around cursor (CSS px)

    // Theme colors â€” match the page accent palette
    const BASE_DOT  = 'rgba(150, 175, 220, 0.10)'; // subtle resting state on dark bg
    const GLOW_RGB  = '0, 212, 216';                // cyan accent
    const GLOW_RGB2 = '96, 165, 250';               // blue accent
    const GLOW_RGB3 = '168, 85, 247';               // purple accent

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      dotsCanvas.width = Math.round(W * dpr);
      dotsCanvas.height = Math.round(H * dpr);
      dotsCanvas.style.width = W + 'px';
      dotsCanvas.style.height = H + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = Math.ceil(W / SPACING) + 2;
      rows = Math.ceil(H / SPACING) + 2;
    }
    resize();

    let resizeT;
    window.addEventListener('resize', () => {
      clearTimeout(resizeT);
      resizeT = setTimeout(resize, 120);
    });

    window.addEventListener('mousemove', (e) => {
      targetX = e.clientX;
      targetY = e.clientY;
      hasCursor = true;
      document.documentElement.style.setProperty('--mx', e.clientX + 'px');
      document.documentElement.style.setProperty('--my', e.clientY + 'px');
      document.body.classList.add('has-cursor');
    });

    window.addEventListener('mouseleave', () => {
      // Smoothly retreat off-screen
      targetX = -9999;
      targetY = -9999;
      hasCursor = false;
      document.body.classList.remove('has-cursor');
    });

    // Smoothly chase the cursor for a softer feel
    function step() {
      const ease = 0.18;
      mouseX += (targetX - mouseX) * ease;
      mouseY += (targetY - mouseY) * ease;
      drawDots();
      requestAnimationFrame(step);
    }

    function drawDots() {
      ctx.clearRect(0, 0, W, H);

      // Pre-square the influence radius for fast distÂ² compare
      const inf2 = INFLUENCE * INFLUENCE;

      // Slight time-based shimmer for liveliness
      const t = performance.now() * 0.0008;

      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          // Stagger every other row by half a step for a denser, hex-ish pattern
          const offsetX = (r % 2) * (SPACING / 2);
          const x = c * SPACING + offsetX - SPACING / 2;
          const y = r * SPACING - SPACING / 2;

          const dx = x - mouseX;
          const dy = y - mouseY;
          const d2 = dx * dx + dy * dy;

          if (hasCursor && d2 < inf2) {
            const d = Math.sqrt(d2);
            const t01 = 1 - d / INFLUENCE;          // 0..1 closeness
            const eased = t01 * t01;                 // sharper falloff

            // Color blends through cyan â†’ blue â†’ purple as you move,
            // with a tiny shimmer driven by position so it feels alive.
            const shimmer = 0.85 + 0.15 * Math.sin(t * 6 + (r + c) * 0.7);
            const radius = RADIUS + eased * 2.6 * shimmer;
            const alpha = 0.18 + eased * 0.85 * shimmer;

            // Pick one of three accent colors based on angle from cursor
            const ang = Math.atan2(dy, dx);
            // Map angle (-Ï€..Ï€) into a 0..3 segment
            const seg = ((ang + Math.PI) / (Math.PI * 2)) * 3;
            const rgb =
              seg < 1 ? GLOW_RGB :
              seg < 2 ? GLOW_RGB2 :
                        GLOW_RGB3;

            // Outer glow halo (additive feel via low alpha)
            ctx.beginPath();
            ctx.fillStyle = `rgba(${rgb}, ${alpha * 0.25})`;
            ctx.arc(x, y, radius * 2.4, 0, Math.PI * 2);
            ctx.fill();

            // Core dot
            ctx.beginPath();
            ctx.fillStyle = `rgba(${rgb}, ${alpha})`;
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fill();
          } else {
            ctx.beginPath();
            ctx.fillStyle = BASE_DOT;
            ctx.arc(x, y, RADIUS, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
    }

    requestAnimationFrame(step);
  }

  /* =================================================================
     3) INTERACTIVE WORDMARK (cursor-driven gradient hot-spot)
     ================================================================= */

  const wm = document.getElementById('hero-wordmark');
  if (wm && !prefersReduced && !isTouch) {
    let inside = false;

    const setHotspot = (x, y) => {
      wm.style.setProperty('--wm-x', x + 'px');
      wm.style.setProperty('--wm-y', y + 'px');
    };

    // Default centred hot-spot
    requestAnimationFrame(() => {
      const r = wm.getBoundingClientRect();
      setHotspot(r.width / 2, r.height / 2);
    });

    wm.addEventListener('mousemove', (e) => {
      const r = wm.getBoundingClientRect();
      setHotspot(e.clientX - r.left, e.clientY - r.top);
      if (!inside) {
        inside = true;
        wm.style.setProperty('--wm-intensity', '1');
      }
    });

    wm.addEventListener('mouseleave', () => {
      inside = false;
      wm.style.setProperty('--wm-intensity', '0');
    });

    // Even when the mouse is anywhere on the page, gently lean the gradient
    // toward the cursor â€” gives the wordmark a subtle parallax life.
    window.addEventListener('mousemove', (e) => {
      if (inside) return;
      const r = wm.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      // Map page distance to local position with damping
      const lx = r.width / 2 + Math.max(-r.width / 2, Math.min(r.width / 2, dx * 0.35));
      const ly = r.height / 2 + Math.max(-r.height / 2, Math.min(r.height / 2, dy * 0.35));
      setHotspot(lx, ly);
    });
  }

  /* =================================================================
     4) BILLING CYCLE TOGGLE
     ================================================================= */

  const toggleBtns = document.querySelectorAll('.toggle-btn');
  toggleBtns.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      // Annual billing is disabled â€” coming soon. Block any switch.
      if (btn.classList.contains('is-disabled') || btn.getAttribute('aria-disabled') === 'true') {
        e.preventDefault();
        return;
      }
      const cycle = btn.dataset.cycle;
      if (cycle === currentCycle) return;
      currentCycle = cycle;

      toggleBtns.forEach((b) => {
        const on = b.dataset.cycle === cycle;
        if (b.classList.contains('is-disabled')) return; // never activate disabled
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });

      updatePrices(cycle);
    });
  });

  function updatePrices(cycle) {
    document.querySelectorAll('.plan-price-amount').forEach((el) => {
      const target = parseFloat(el.dataset[cycle]);
      const start = parseFloat(el.textContent) || 0;
      animateNumber(el, start, target, 380);
    });
  }

  function animateNumber(el, from, to, duration) {
    if (prefersReduced) {
      el.textContent = formatPrice(to);
      return;
    }
    const t0 = performance.now();
    const delta = to - from;
    function frame(now) {
      const p = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = formatPrice(from + delta * eased);
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function formatPrice(n) {
    if (n === 0) return '0';
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }

  /* =================================================================
     5) SUBSCRIBE HANDLER
     ================================================================= */
  window.subscribe = function subscribe(tier) {
    const priceId = PRICE_IDS[tier]?.[currentCycle];
    if (!priceId) return;
    const endpoint = '/api/checkout';

    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier, cycle: currentCycle, priceId }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data && data.url) window.location.href = data.url;
        else
          alert(
            `[stub] Would redirect to Stripe Checkout for ${tier.toUpperCase()} Â· ${currentCycle} (${priceId})`
          );
      })
      .catch(() => {
        alert(
          `[stub] Would redirect to Stripe Checkout for ${tier.toUpperCase()} Â· ${currentCycle} (${priceId})`
        );
      });
  };

  /* =================================================================
     6) 3D TILT ON CARDS
     ================================================================= */
  if (!prefersReduced && !isTouch) {
    const cards = document.querySelectorAll('.plan');
    cards.forEach((card) => {
      const inner = card.querySelector('.plan-inner');
      if (!inner) return;

      card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const rx = ((y / rect.height) - 0.5) * -6;
        const ry = ((x / rect.width) - 0.5) *  6;
        inner.style.transform =
          `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) translateY(-4px)`;
      });

      card.addEventListener('mouseleave', () => {
        inner.style.transform = '';
      });
    });
  }

  /* =================================================================
     7) KEYBOARD: Enter/Space on focused card subscribes
     ================================================================= */
  document.querySelectorAll('.plan').forEach((card) => {
    card.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const tag = (document.activeElement?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'button') return;
      e.preventDefault();
      const tier = card.dataset.plan;
      if (tier && tier !== 'free') window.subscribe(tier);
    });
  });
})();

