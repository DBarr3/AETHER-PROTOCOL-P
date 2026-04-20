import React, { useEffect, useRef } from "react";

const VS = `
attribute vec2 a_position;
varying vec2 v_uv;
void main() {
    v_uv = a_position * 0.5 + 0.5;
    gl_Position = vec4(a_position, 0.0, 1.0);
}`;

const FS = `
precision highp float;
varying vec2 v_uv;
uniform sampler2D u_earthTex;
uniform float u_rotation;
uniform float u_sR;
#define PI 3.14159265359

void main() {
    float nx = v_uv.x * 2.0 - 1.0;
    float ny = v_uv.y * 2.0 - 1.0;
    float nz2 = 1.0 - nx*nx - ny*ny;
    if (nz2 < 0.0) { discard; }
    float nz = sqrt(nz2);

    float lat = asin(ny);
    float lon = atan(nx, nz) + u_rotation;
    float u = mod((lon / (2.0 * PI)) + 0.5, 1.0);
    float v = 0.5 - lat / PI;
    vec4 texColor = texture2D(u_earthTex, vec2(u, v));

    float r_tex = texColor.r * 255.0;
    float g_tex = texColor.g * 255.0;
    float b_tex = texColor.b * 255.0;

    float LX = -0.28, LY = 0.42, LZ = 0.86;
    float diff = nx*LX + (-ny)*LY + nz*LZ;
    float terminator = pow(max(0.0, diff / 0.22), 0.52);
    float ambient = 0.055;
    float light = ambient + (1.0 - ambient) * terminator;

    float isNight = diff < 0.08 ? 1.0 : 0.0;
    float fr = r_tex * light + isNight * r_tex * 0.12;
    float fg = g_tex * light + isNight * g_tex * 0.08;
    float fb = b_tex * light + isNight * b_tex * 0.04;

    float limb_r = sqrt(nx*nx + ny*ny);
    float limb = pow(max(0.0, (limb_r - 0.90) / 0.10), 1.8);
    fr = min(255.0, fr + limb * 35.0);
    fg = min(255.0, fg + limb * 90.0);
    fb = min(255.0, fb + limb * 200.0);

    float ref = nz * 2.0 * max(0.0, diff) - LZ;
    float spec = pow(max(0.0, ref), 40.0) * 0.35;
    fr = min(255.0, fr + spec * 200.0);
    fg = min(255.0, fg + spec * 210.0);
    fb = min(255.0, fb + spec * 230.0);

    float edge_aa = min(1.0, (1.0 - limb_r) * u_sR * 0.8);
    gl_FragColor = vec4(fr / 255.0, fg / 255.0, fb / 255.0, edge_aa);
}`;

function createShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error(gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function initStars(starCanvas, starCtx, W, H, dpr) {
  const sw = W * dpr;
  const sh = H * dpr;
  starCanvas.width = sw;
  starCanvas.height = sh;

  starCtx.fillStyle = "#020810";
  starCtx.fillRect(0, 0, sw, sh);

  const rng = (n) => Math.random() * n;
  for (let i = 0; i < 350; i++) {
    const x = rng(sw);
    const y = rng(sh);
    const tier = Math.random();
    const radius = tier < 0.75 ? 0.8 : tier < 0.93 ? 1.4 : 2.0;
    const alpha = tier < 0.75 ? rng(0.4) + 0.3 : tier < 0.93 ? rng(0.4) + 0.5 : rng(0.3) + 0.7;
    const warm = Math.random();

    const cr = warm < 0.7 ? 255 : warm < 0.85 ? 255 : 200;
    const cg = warm < 0.7 ? 255 : warm < 0.85 ? 245 : 220;
    const cb = warm < 0.7 ? 255 : warm < 0.85 ? 220 : 255;

    starCtx.globalAlpha = alpha;
    starCtx.fillStyle = `rgb(${cr},${cg},${cb})`;

    if (tier >= 0.93) {
      starCtx.shadowBlur = tier >= 0.98 ? 16 : 8;
      starCtx.shadowColor = `rgb(${cr},${cg},${cb})`;
    } else {
      starCtx.shadowBlur = 0;
    }

    starCtx.beginPath();
    starCtx.arc(x, y, radius, 0, Math.PI * 2);
    starCtx.fill();
    starCtx.shadowBlur = 0;
  }

  const mw = starCtx.createLinearGradient(0, sh * 0.2, sw, sh * 0.8);
  mw.addColorStop(0, "rgba(255,255,255,0)");
  mw.addColorStop(0.3, "rgba(200,215,255,0.025)");
  mw.addColorStop(0.5, "rgba(210,220,255,0.04)");
  mw.addColorStop(0.7, "rgba(200,215,255,0.025)");
  mw.addColorStop(1, "rgba(255,255,255,0)");
  starCtx.globalAlpha = 1;
  starCtx.fillStyle = mw;
  starCtx.fillRect(0, 0, sw, sh);
}

export default function SpinningGlobe() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const globeConfig = { cx: 0.5, cy: 0.54, R: 0.62 };
    const SUPERSAMPLE = 2;
    const SPIN_SPEED = 0.000045;

    let dpr = 1;
    let W = 0, H = 0, cx = 0, cy = 0, R = 0, sR = 0;
    let startTime = null;
    let rafId = null;
    let loaded = false;

    const starCanvas = document.createElement("canvas");
    const starCtx = starCanvas.getContext("2d", { alpha: true });

    const glCanvas = document.createElement("canvas");
    const gl =
      glCanvas.getContext("webgl", { preserveDrawingBuffer: true, antialias: true, premultipliedAlpha: false }) ||
      glCanvas.getContext("experimental-webgl", { preserveDrawingBuffer: true, antialias: true, premultipliedAlpha: false });

    if (!gl) return;

    // Build shader program
    const program = gl.createProgram();
    gl.attachShader(program, createShader(gl, gl.VERTEX_SHADER, VS));
    gl.attachShader(program, createShader(gl, gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(program);
    gl.useProgram(program);

    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);

    const posLocation = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(posLocation);
    gl.vertexAttribPointer(posLocation, 2, gl.FLOAT, false, 0, 0);

    const rotLoc = gl.getUniformLocation(program, "u_rotation");
    const srLoc = gl.getUniformLocation(program, "u_sR");

    // Texture
    const earthTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, earthTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (!gl) return;
      gl.bindTexture(gl.TEXTURE_2D, earthTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
      loaded = true;
    };
    img.src = "/assets/earth_equirectangular.webp";
    if (img.complete && img.naturalWidth > 0) img.onload();

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;

      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);

      cx = W * globeConfig.cx;
      cy = H * globeConfig.cy;
      R = Math.min(W, H) * globeConfig.R;
      sR = Math.floor(R * SUPERSAMPLE);

      glCanvas.width = sR * 2;
      glCanvas.height = sR * 2;
      gl.viewport(0, 0, sR * 2, sR * 2);

      initStars(starCanvas, starCtx, W, H, dpr);
    }

    function renderGlobe(rotationAngle) {
      if (sR === 0 || !loaded) return;
      gl.clearColor(0.0, 0.0, 0.0, 0.0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(rotLoc, rotationAngle);
      gl.uniform1f(srLoc, sR);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }

    function loop(timestamp) {
      rafId = requestAnimationFrame(loop);
      if (!startTime) startTime = timestamp;
      const elapsed = timestamp - startTime;

      ctx.drawImage(starCanvas, 0, 0, W, H);
      if (!loaded) return;

      const rotAngle = (elapsed * SPIN_SPEED) % (Math.PI * 2);
      renderGlobe(rotAngle);

      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(glCanvas, cx - R, cy - R, R * 2, R * 2);

      // Vignette around globe
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.clip();
      const edge = ctx.createRadialGradient(cx, cy, R * 0.6, cx, cy, R);
      edge.addColorStop(0, "rgba(0,0,0,0)");
      edge.addColorStop(0.72, "rgba(0,0,0,0.10)");
      edge.addColorStop(1, "rgba(0,0,0,0.75)");
      ctx.fillStyle = edge;
      ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
      ctx.restore();

      // Scene vignette
      const cv = ctx.createRadialGradient(W * 0.5, H * 0.5, H * 0.3, W * 0.5, H * 0.5, H * 0.88);
      cv.addColorStop(0, "rgba(0,0,0,0)");
      cv.addColorStop(1, "rgba(0,0,0,0.55)");
      ctx.fillStyle = cv;
      ctx.fillRect(0, 0, W, H);

      // Inner shadow
      const tv = ctx.createRadialGradient(W * 0.5, H * 0.48, R * 0.08, W * 0.5, H * 0.5, R * 0.88);
      tv.addColorStop(0, "rgba(2,8,16,0.52)");
      tv.addColorStop(0.4, "rgba(2,8,16,0.14)");
      tv.addColorStop(1, "rgba(2,8,16,0)");
      ctx.fillStyle = tv;
      ctx.fillRect(0, 0, W, H);
    }

    window.addEventListener("resize", resize);
    resize();
    rafId = requestAnimationFrame(loop);

    return () => {
      window.removeEventListener("resize", resize);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none fixed inset-0 z-0"
      aria-hidden="true"
    />
  );
}
