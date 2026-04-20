// AetherCloud reactive dot background — transparent layer
(() => {
  const container = document.getElementById('dotBackground');
  const canvas = document.getElementById('dotCanvas');
  if (!container || !canvas) return;
  const ctx = canvas.getContext('2d');

  let dots = [];
  const pointer = { x: -9999, y: -9999, active: false };

  function buildDots(width, height) {
    const spacing = 26;
    const cols = Math.max(12, Math.floor(width / spacing));
    const rows = Math.max(10, Math.floor(height / spacing));
    const list = [];
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        list.push({
          x: 16 + x * spacing + (y % 2 ? 2 : 0),
          y: 16 + y * spacing,
          baseR: 0.9 + Math.random() * 0.7,
          glow: 0,
          pulseSeed: Math.random() * Math.PI * 2
        });
      }
    }
    return list;
  }

  function resize() {
    const rect = container.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    dots = buildDots(rect.width, rect.height);
  }

  function draw() {
    const rect = container.getBoundingClientRect();
    ctx.clearRect(0, 0, rect.width, rect.height);

    for (const dot of dots) {
      const dx = pointer.x - dot.x;
      const dy = pointer.y - dot.y;
      const dist = Math.hypot(dx, dy);
      const hover = pointer.active ? Math.max(0, 1 - dist / 110) : 0;
      dot.glow += (hover - dot.glow) * 0.14;

      const pulse = 0.10 + ((Math.sin(performance.now() * 0.0013 + dot.pulseSeed) + 1) * 0.05);
      const radius = dot.baseR + dot.glow * 2.4;
      const alpha = 0.10 + pulse + dot.glow * 0.48;

      if (dot.glow > 0.02) {
        const g = ctx.createRadialGradient(dot.x, dot.y, 0, dot.x, dot.y, 18 + dot.glow * 20);
        g.addColorStop(0, `rgba(137,220,255,${0.10 + dot.glow * 0.22})`);
        g.addColorStop(0.45, `rgba(139,144,255,${0.06 + dot.glow * 0.14})`);
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(dot.x, dot.y, 18 + dot.glow * 20, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.fillStyle = `rgba(180,210,255,${alpha})`;
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }

    requestAnimationFrame(draw);
  }

  // Track pointer over the whole window (so hovering over UI still lights up dots)
  window.addEventListener('mousemove', (e) => {
    const rect = container.getBoundingClientRect();
    pointer.x = e.clientX - rect.left;
    pointer.y = e.clientY - rect.top;
    pointer.active = true;
  });
  window.addEventListener('mouseleave', () => { pointer.active = false; pointer.x = -9999; pointer.y = -9999; });
  window.addEventListener('blur', () => { pointer.active = false; });
  window.addEventListener('resize', resize);

  resize();
  draw();
})();
