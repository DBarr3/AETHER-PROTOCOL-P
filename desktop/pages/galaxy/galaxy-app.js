// galaxy-app.js
// ---------------------------------------------------------------------
// AetherCloud Vault -- single-tier 3D space with Vault Star anchor.
//
// Architecture:
//   ONE scene. All projects always present. Camera is the only thing
//   that moves on navigation. No universe/system tier split. No warp.
//
//   A central VAULT STAR at the origin acts as the gravitational anchor.
//   Projects are arranged in angular wedges around it, grouped by
//   source-folder cluster (Desktop, Downloads, Documents, Projects,
//   Code, Other). Each cluster has a tinted ring, label, and backbone
//   edges connecting its members back to the Vault Star.
//
//   Each project is a "constellation" -- a THREE.Group containing:
//     - root icon sprite (72px overlay)
//     - cluster-tinted halo (additive blending)
//     - project label (SpriteText, textHeight 5.0)
//     - filesContainer sub-group (file sprites + file labels)
//     - edgesContainer sub-group (project-center-to-file lines)
//
//   Distance-based LOD toggles filesContainer and edgesContainer
//   visibility per group so 50+ projects stay performant.
//
//   Constants:
//     R_FILES             = 36   -- file sprite orbit radius
//     SHELL_RADIUS        = 320  -- inner shell for project placement
//     SHELL_RADIUS_OUTER  = 520  -- outer shell for staggered projects
//     HOME_POS            = (0, 120, 700) -- camera home / ESC target
//
// Mount: auto-installs a hook into window.switchViewMode and reveals
// the vault 3D scene when the user picks the "VAULT" view.
// ---------------------------------------------------------------------
(function () {
  if (typeof window === "undefined") return;
  if (window.aetherGalaxyApp && window.aetherGalaxyApp.__installed) return;

  if (!window.THREE || !window.ForceGraph3D || !window.SpriteText) {
    console.warn("[vault3d] vendor globals missing -- galaxy-app.js loaded out of order?");
    return;
  }
  if (!window.aetherGalaxy) {
    console.warn("[vault3d] window.aetherGalaxy IPC bridge not exposed -- preload.js may be stale.");
    return;
  }

  var THREE = window.THREE;
  var SpriteText = window.SpriteText;
  var OrbitControls = window.OrbitControls;
  var ipc = window.aetherGalaxy;

  // == Architecture constants =========================================
  var R_FILES           = 36;
  var LOD_FULL          = 180;
  var LOD_MEDIUM        = 500;
  var MEDIUM_FILE_CAP   = 12;
  var SHELL_RADIUS      = 320;
  var SHELL_RADIUS_OUTER = 520;
  var HOME_POS          = { x: 0, y: 120, z: 700 };

  // Cluster tints -- hex for THREE, CSS for SpriteText
  var CLUSTER_ORDER = ["Desktop", "Downloads", "Documents", "Projects", "Code", "Other"];
  var CLUSTER_TINTS = {
    Desktop:   0xfbbf24,
    Downloads: 0x38bdf8,
    Documents: 0xa78bfa,
    Projects:  0x5eead4,
    Code:      0x4ade80,
    Other:     0x94a3b8,
  };
  var CLUSTER_CSS = {
    Desktop:   "#fbbf24",
    Downloads: "#38bdf8",
    Documents: "#a78bfa",
    Projects:  "#5eead4",
    Code:      "#4ade80",
    Other:     "#94a3b8",
  };

  // == Source-folder clustering ========================================
  function deriveSourceCluster(manifest) {
    var p = String(manifest.path || manifest.name || "").toLowerCase();
    if (/desktop/.test(p))                          return "Desktop";
    if (/download/.test(p))                         return "Downloads";
    if (/doc|pdf|patent|report|archive/.test(p))    return "Documents";
    if (/project|workspace/.test(p))                return "Projects";
    if (/code|dev|src|github|repo|engine|mirror/.test(p)) return "Code";
    return "Other";
  }

  // == Deterministic wedge layout =====================================
  // Places projects on angular wedges per cluster around the origin.
  // Returns { positions: Map<id,{x,y,z}>, clusterAngles, activeClusters, clusterMap }
  function layoutProjects(manifests) {
    var clusters = {};
    for (var mi = 0; mi < manifests.length; mi++) {
      var m = manifests[mi];
      var c = deriveSourceCluster(m);
      if (!clusters[c]) clusters[c] = [];
      clusters[c].push(m);
    }

    var active = [];
    for (var ci = 0; ci < CLUSTER_ORDER.length; ci++) {
      var cn = CLUSTER_ORDER[ci];
      if (clusters[cn] && clusters[cn].length > 0) active.push(cn);
    }

    var wedge = (2 * Math.PI) / Math.max(1, active.length);
    var positions = new Map();
    var clusterAngles = new Map();

    for (var ai = 0; ai < active.length; ai++) {
      var cName = active[ai];
      var midAngle = ai * wedge;
      clusterAngles.set(cName, midAngle);
      var members = clusters[cName];
      var n = members.length;

      for (var i = 0; i < n; i++) {
        var spread = wedge * 0.65;
        var angle = n === 1
          ? midAngle
          : midAngle - spread / 2 + (i / (n - 1)) * spread;
        // Stagger inner / mid / outer ring to avoid straight line
        var ringIdx = i % 3;
        var radius = SHELL_RADIUS + ringIdx * ((SHELL_RADIUS_OUTER - SHELL_RADIUS) / 2);
        var yOff = ((i % 3) - 1) * 30;

        positions.set(members[i].id, {
          x: Math.cos(angle) * radius,
          y: yOff,
          z: Math.sin(angle) * radius,
        });
      }
    }

    return {
      positions: positions,
      clusterAngles: clusterAngles,
      activeClusters: active,
      clusterMap: clusters,
    };
  }

  // == Shared circular sprite texture =================================
  var CIRCLE_TEX = null;
  function makeCircleTexture() {
    if (CIRCLE_TEX) return CIRCLE_TEX;
    var cv = document.createElement("canvas");
    cv.width = cv.height = 128;
    var ctx = cv.getContext("2d");
    var g = ctx.createRadialGradient(64, 64, 0, 64, 64, 60);
    g.addColorStop(0,    "rgba(255,255,255,1)");
    g.addColorStop(0.25, "rgba(255,255,255,0.7)");
    g.addColorStop(0.5,  "rgba(255,255,255,0.15)");
    g.addColorStop(0.75, "rgba(255,255,255,0.03)");
    g.addColorStop(1,    "rgba(255,255,255,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, 128, 128);
    CIRCLE_TEX = new THREE.CanvasTexture(cv);
    CIRCLE_TEX.magFilter = THREE.LinearFilter;
    CIRCLE_TEX.minFilter = THREE.LinearMipmapLinearFilter;
    CIRCLE_TEX.generateMipmaps = true;
    return CIRCLE_TEX;
  }

  // == PNG icon textures ==============================================
  var ICON_BASE = "./vault-graph-3d/icons";
  var ICON_NAMES = [
    "img","doc","pdf","md","json","yaml","py","ts","csv","log","env","bin","key",
    "folder","folder_secret","folder_doc","folder_strategy","folder_model","folder_sec",
    "root","star",
  ];
  var ICON_TEX = {};
  var ICON_MATS = {};
  var ICON_LOADED = false;
  function preloadIconTextures() {
    if (ICON_LOADED) return;
    ICON_LOADED = true;
    var loader = new THREE.TextureLoader();
    for (var ki = 0; ki < ICON_NAMES.length; ki++) {
      var k = ICON_NAMES[ki];
      ICON_MATS[k] = [];
      var t = loader.load(
        ICON_BASE + "/" + k + ".png",
        (function (key) {
          return function (tex) {
            if (THREE.SRGBColorSpace) tex.colorSpace = THREE.SRGBColorSpace;
            tex.needsUpdate = true;
            for (var mi = 0; mi < ICON_MATS[key].length; mi++) ICON_MATS[key][mi].needsUpdate = true;
          };
        })(k),
        undefined,
        (function (key) {
          return function () { console.warn("[vault3d] icon load failed:", key); };
        })(k)
      );
      t.minFilter = THREE.LinearFilter;
      t.magFilter = THREE.LinearFilter;
      t.generateMipmaps = false;
      ICON_TEX[k] = t;
    }
  }

  var ICON_FALLBACK_TEX = {};
  function getFallbackTex(key) {
    if (ICON_FALLBACK_TEX[key]) return ICON_FALLBACK_TEX[key];
    var cv = document.createElement("canvas");
    cv.width = cv.height = 128;
    var ctx = cv.getContext("2d");
    var color = "#" + iconFallbackColor(key).toString(16).padStart(6, "0");
    ctx.clearRect(0, 0, 128, 128);
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(64, 64, 52, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "rgba(0,0,0,0.55)";
    ctx.font = "bold 44px monospace";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(key.slice(0, 3).toUpperCase(), 64, 66);
    var tex = new THREE.CanvasTexture(cv);
    tex.magFilter = THREE.LinearFilter;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.generateMipmaps = true;
    ICON_FALLBACK_TEX[key] = tex;
    return tex;
  }

  function makeIconSpriteRaw(iconKey, sizeUnits) {
    var tex = ICON_TEX[iconKey] || ICON_TEX.doc || getFallbackTex(iconKey);
    var mat = new THREE.SpriteMaterial({
      map: tex,
      transparent: true,
      depthWrite: false,
      depthTest: true,
      alphaTest: 0.01,
    });
    if (ICON_MATS[iconKey]) ICON_MATS[iconKey].push(mat);
    var s = new THREE.Sprite(mat);
    s.scale.set(sizeUnits, sizeUnits, 1);
    s.renderOrder = 10;
    return s;
  }

  // == Icon helpers ===================================================
  function pickIconKey(name, opts) {
    var fn = window.AETHER_VAULT_ICONS && window.AETHER_VAULT_ICONS.iconKeyFor;
    if (typeof fn === "function") return fn(name, opts);
    return "doc";
  }
  function iconFallbackColor(key) {
    var m = {
      img: 0xfb923c, doc: 0xf87171, pdf: 0xef4444, md: 0xfca5a5,
      json: 0xa78bfa, yaml: 0xc4b5fd, py: 0x86efac, ts: 0xfbbf24,
      csv: 0xddd6fe, log: 0x94a3b8, env: 0xf59e0b, bin: 0xa1a1aa, key: 0xfde047,
      root: 0x5eead4, star: 0xa78bfa,
    };
    return m[key] || 0xe2e8f0;
  }

  // == Utility helpers ================================================
  function recencyToOpacity(lastTouchedAt) {
    if (!lastTouchedAt) return 0;
    var ageMs = Date.now() - lastTouchedAt;
    if (ageMs <= 0) return 1;
    var HALF_LIFE_MS = 24 * 60 * 60 * 1000;
    var opacity = Math.pow(0.5, ageMs / HALF_LIFE_MS);
    return opacity > 0.1 ? opacity : 0;
  }

  function disposeGroup(group) {
    if (!group) return;
    group.traverse(function (obj) {
      if (obj.isMesh || obj.isLine || obj.isPoints) {
        if (obj.geometry) obj.geometry.dispose();
        var mats = Array.isArray(obj.material) ? obj.material : [obj.material];
        for (var mi = 0; mi < mats.length; mi++) {
          var mat = mats[mi];
          if (!mat) continue;
          var keys = Object.keys(mat);
          for (var ki = 0; ki < keys.length; ki++) {
            var v = mat[keys[ki]];
            if (v && v.isTexture) v.dispose();
          }
          mat.dispose();
        }
      }
    });
  }

  function basename(p) {
    var s = String(p || "");
    var slash = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
    return slash >= 0 ? s.slice(slash + 1) : s;
  }

  // Synthetic file counts for demo manifests
  var SYNTH_COUNTS = {};

  // == Resolve file list for a project ================================
  function getProjectFiles(manifest) {
    if (manifest.id === "local:vault") {
      var entries = readVaultEntries();
      return entries.map(function (n, i) {
        return { path: n.path || n.name || "file_" + i };
      });
    }
    var count = manifest.fileCount || SYNTH_COUNTS[manifest.id] || 0;
    var exts = ["md", "py", "ts", "json", "yaml", "pdf", "log", "env"];
    var files = [];
    for (var i = 0; i < count; i++) {
      files.push({ path: "file_" + i + "." + exts[i % exts.length] });
    }
    return files;
  }

  // ===================================================================
  // VaultSceneManager -- single-tier 3D space with Vault Star anchor
  // ===================================================================
  class VaultSceneManager {
    constructor(host) {
      this.host = host;
      this.scene = new THREE.Scene();
      this.camera = new THREE.PerspectiveCamera(60, 1, 0.1, 8000);
      this.camera.position.set(HOME_POS.x, HOME_POS.y, HOME_POS.z);
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      this.renderer.setPixelRatio(window.devicePixelRatio || 1);
      this.renderer.setClearColor(0x05070d, 1);
      this.renderer.outputColorSpace = THREE.SRGBColorSpace || THREE.sRGBEncoding;
      host.appendChild(this.renderer.domElement);

      // HTML icon overlay
      this.overlayEl = document.createElement("div");
      this.overlayEl.style.cssText =
        "position:absolute;top:0;left:0;width:100%;height:100%;" +
        "pointer-events:none;z-index:3;overflow:hidden;";
      host.appendChild(this.overlayEl);
      this.iconElMap = new Map();
      this._projVec = new THREE.Vector3();

      // Single-tier state
      this.focusedProjectId = null;
      this.projectGroups = new Map();
      this.projectMeta   = new Map();
      this._clickTargets = [];

      // Vault Star, backbone edges, cluster visuals
      this.vaultStarGroup = null;
      this._vaultStarHalo = null;
      this.backboneGroup  = new THREE.Group();
      this.clusterGroup   = new THREE.Group();
      this.arcGroup       = new THREE.Group();
      this.scene.add(this.backboneGroup);
      this.scene.add(this.clusterGroup);
      this.scene.add(this.arcGroup);

      // Fog for the larger space
      this.scene.fog = new THREE.FogExp2(0x05070d, 0.0008);

      this._raf = 0;
      this._disposed = false;
      this._addStarfield();
      this._installResize();
      this._installOrbitControls();
      this._installInteraction();
      this._installEscKey();
      this._loop();
      makeCircleTexture();
      preloadIconTextures();
    }

    _installOrbitControls() {
      if (!OrbitControls) {
        console.warn("[vault3d] OrbitControls not in bundle");
        return;
      }
      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping  = true;
      this.controls.dampingFactor  = 0.08;
      this.controls.enablePan      = true;
      this.controls.rotateSpeed    = 0.7;
      this.controls.zoomSpeed      = 1.4;
      this.controls.minDistance     = 20;
      this.controls.maxDistance     = 2000;
      this.controls.target.set(0, 0, 0);
    }

    // -- ESC key handler ----------------------------------------------
    _installEscKey() {
      var self = this;
      this._onKeyDown = function (e) {
        if (e.key === "Escape") {
          e.preventDefault();
          self.flyToOverview();
        }
      };
      document.addEventListener("keydown", this._onKeyDown);
    }

    // =================================================================
    // Build the entire vault
    // =================================================================
    async buildVault(manifests) {
      // Dispose existing project constellations
      for (var _i = 0, _a = Array.from(this.projectGroups.values()); _i < _a.length; _i++) {
        disposeGroup(_a[_i]);
        this.scene.remove(_a[_i]);
      }
      this.projectGroups.clear();
      this.projectMeta.clear();
      this._clickTargets = [];
      this._gcOverlayIcons();

      // Dispose vault star
      if (this.vaultStarGroup) {
        disposeGroup(this.vaultStarGroup);
        this.scene.remove(this.vaultStarGroup);
        this.vaultStarGroup = null;
        this._vaultStarHalo = null;
      }

      // Clear backbone edges
      while (this.backboneGroup.children.length) {
        var bc = this.backboneGroup.children[0];
        if (bc.geometry) bc.geometry.dispose();
        if (bc.material) bc.material.dispose();
        this.backboneGroup.remove(bc);
      }

      // Clear cluster visuals (rings + labels)
      while (this.clusterGroup.children.length) {
        var cc = this.clusterGroup.children[0];
        if (cc.geometry) cc.geometry.dispose();
        if (cc.material) cc.material.dispose();
        this.clusterGroup.remove(cc);
      }

      // -- Wedge layout -----------------------------------------------
      var layout = layoutProjects(manifests);

      // -- Build Vault Star at origin ----------------------------------
      this._buildVaultStar();

      // -- Build every project constellation ---------------------------
      for (var mi = 0; mi < manifests.length; mi++) {
        var m = manifests[mi];
        var pos = layout.positions.get(m.id);
        if (!pos) continue;
        this.projectMeta.set(m.id, m);

        var files = getProjectFiles(m);
        var clusterName = deriveSourceCluster(m);
        var group = this._buildConstellation(m, files, clusterName);
        group.position.set(pos.x, pos.y, pos.z);
        this.scene.add(group);
        this.projectGroups.set(m.id, group);

        // Backbone edge: vault star (origin) --> project
        var bGeom = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(0, 0, 0),
          new THREE.Vector3(pos.x, pos.y, pos.z),
        ]);
        var bMat = new THREE.LineBasicMaterial({
          color: 0x5eead4, transparent: true, opacity: 0.10,
        });
        this.backboneGroup.add(new THREE.Line(bGeom, bMat));
      }

      // -- Cluster rings and labels ------------------------------------
      for (var ai = 0; ai < layout.activeClusters.length; ai++) {
        var cName   = layout.activeClusters[ai];
        var cAngle  = layout.clusterAngles.get(cName);
        var members = layout.clusterMap[cName];
        var tint    = CLUSTER_TINTS[cName] || 0x94a3b8;
        var tintCss = CLUSTER_CSS[cName]   || "#94a3b8";

        // Cluster ring (connecting line through members)
        if (members.length >= 2) {
          this._buildClusterRing(members, tint, layout.positions);
        }

        // Cluster label at outer wedge edge
        var labelPos = new THREE.Vector3(
          Math.cos(cAngle) * (SHELL_RADIUS_OUTER + 80),
          5,
          Math.sin(cAngle) * (SHELL_RADIUS_OUTER + 80)
        );
        var cLabel = new SpriteText(cName.toUpperCase());
        cLabel.color           = tintCss;
        cLabel.backgroundColor = false;
        cLabel.padding         = 0;
        cLabel.textHeight      = 12;
        cLabel.fontFace        = "JetBrains Mono, ui-monospace, monospace";
        cLabel.fontWeight      = "700";
        cLabel.strokeWidth     = 1.0;
        cLabel.strokeColor     = "#020617";
        cLabel.material.depthWrite   = false;
        cLabel.material.transparent  = true;
        cLabel.renderOrder     = 22;
        cLabel.position.copy(labelPos);
        cLabel.userData = { kind: "clusterLabel" };
        this.clusterGroup.add(cLabel);
      }

      // -- Collect click targets (halo + root icon sprites) ------------
      for (var _ii = 0, _aa = Array.from(this.projectGroups.values()); _ii < _aa.length; _ii++) {
        var grp = _aa[_ii];
        for (var ci2 = 0; ci2 < grp.children.length; ci2++) {
          var child = grp.children[ci2];
          if (child.isSprite && child.userData &&
              (child.userData.type === "project_halo" ||
               child.userData.type === "project_icon")) {
            this._clickTargets.push(child);
          }
        }
      }

      // Camera to home
      this.focusedProjectId = null;
      this._tweenCamera(HOME_POS, 600, new THREE.Vector3(0, 0, 0));
      this._updateStatusBar();
      this._updateBreadcrumb();
    }

    // =================================================================
    // Vault Star -- central anchor at world origin
    // =================================================================
    _buildVaultStar() {
      var group = new THREE.Group();
      group.userData = { kind: "vaultStar" };

      // Hex sprite
      var hexTex = this._makeHexTexture();
      var hexMat = new THREE.SpriteMaterial({
        map: hexTex,
        color: 0x5eead4,
        transparent: true,
        depthWrite: false,
      });
      var hexSprite = new THREE.Sprite(hexMat);
      hexSprite.scale.set(18, 18, 1);
      hexSprite.renderOrder = 12;
      group.add(hexSprite);

      // Pulsing halo (animated in render loop)
      var haloMap = makeCircleTexture();
      var haloMat = new THREE.SpriteMaterial({
        map: haloMap,
        color: 0x5eead4,
        transparent: true,
        opacity: 0.25,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      var halo = new THREE.Sprite(haloMat);
      halo.scale.set(40, 40, 1);
      halo.renderOrder = 4;
      halo.userData = { type: "vaultStarHalo" };
      group.add(halo);
      this._vaultStarHalo = halo;

      // VAULT label
      var lbl = new SpriteText("VAULT");
      lbl.color           = "#5eead4";
      lbl.backgroundColor = false;
      lbl.padding         = 0;
      lbl.textHeight      = 8;
      lbl.fontFace        = "JetBrains Mono, ui-monospace, monospace";
      lbl.fontWeight      = "700";
      lbl.strokeWidth     = 1.2;
      lbl.strokeColor     = "#020617";
      lbl.material.depthWrite  = false;
      lbl.material.transparent = true;
      lbl.renderOrder     = 21;
      lbl.position.set(0, -18, 0);
      lbl.userData = { kind: "vaultStarLabel" };
      group.add(lbl);

      this.scene.add(group);
      this.vaultStarGroup = group;
    }

    _makeHexTexture() {
      var cv = document.createElement("canvas");
      cv.width = cv.height = 128;
      var ctx = cv.getContext("2d");
      ctx.clearRect(0, 0, 128, 128);
      // Hexagon
      ctx.beginPath();
      for (var i = 0; i < 6; i++) {
        var angle = (Math.PI / 3) * i - Math.PI / 6;
        var px = 64 + 50 * Math.cos(angle);
        var py = 64 + 50 * Math.sin(angle);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fillStyle = "rgba(255,255,255,0.9)";
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.4)";
      ctx.lineWidth = 3;
      ctx.stroke();
      var tex = new THREE.CanvasTexture(cv);
      tex.magFilter = THREE.LinearFilter;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      tex.generateMipmaps = true;
      return tex;
    }

    // =================================================================
    // Cluster ring -- faint tinted line connecting cluster members
    // =================================================================
    _buildClusterRing(members, tint, positions) {
      var points = [];
      for (var i = 0; i < members.length; i++) {
        var p = positions.get(members[i].id);
        if (p) points.push(new THREE.Vector3(p.x, p.y, p.z));
      }
      if (points.length < 2) return;
      // Close loop for 3+ members
      if (points.length >= 3) points.push(points[0].clone());

      var geom = new THREE.BufferGeometry().setFromPoints(points);
      var mat  = new THREE.LineBasicMaterial({
        color: tint, transparent: true, opacity: 0.12,
      });
      this.clusterGroup.add(new THREE.Line(geom, mat));
    }

    // =================================================================
    // Build one project constellation
    // =================================================================
    _buildConstellation(manifest, files, clusterName) {
      var group = new THREE.Group();
      var tint    = CLUSTER_TINTS[clusterName] || 0x94a3b8;
      var tintCss = CLUSTER_CSS[clusterName]   || "#94a3b8";
      group.userData = {
        kind: "project", projectId: manifest.id,
        name: manifest.name, cluster: clusterName,
      };

      // -- Sub-groups for efficient LOD toggling ----------------------
      var filesContainer = new THREE.Group();
      filesContainer.userData = { kind: "filesContainer" };
      var edgesContainer = new THREE.Group();
      edgesContainer.userData = { kind: "edgesContainer" };
      group.add(filesContainer);
      group.add(edgesContainer);

      // -- Root icon anchor (invisible sprite for overlay positioning)
      var rootAnchor = new THREE.Sprite(
        new THREE.SpriteMaterial({ visible: false, depthWrite: false })
      );
      rootAnchor.position.set(0, 0, 0);
      rootAnchor.scale.setScalar(1);
      rootAnchor.userData = { type: "project_icon", projectId: manifest.id };
      group.add(rootAnchor);
      var rootIconKey = pickIconKey(manifest.name || "", { isDirectory: true });
      this._registerIconOverlay(rootAnchor, rootIconKey, 72);

      // -- Halo glow (tinted by cluster) ------------------------------
      var recency = recencyToOpacity(manifest.lastTouchedAt);
      var haloMap = makeCircleTexture();
      var haloMat = new THREE.SpriteMaterial({
        map: haloMap,
        color: tint,
        transparent: true,
        opacity: Math.max(0.15, Math.min(1, 0.12 + recency * 0.2)),
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      var halo = new THREE.Sprite(haloMat);
      var haloScale = 8 + Math.log2((manifest.fileCount || 1) + 1) * 2;
      halo.scale.set(haloScale, haloScale, 1);
      halo.position.set(0, 0, 0);
      halo.userData = {
        type: "project_halo", projectId: manifest.id,
        projectName: manifest.name,
      };
      halo.renderOrder = 5;
      group.add(halo);

      // -- Project label (textHeight = 5.0, cluster-tinted) -----------
      var lbl = new SpriteText(manifest.name || manifest.id);
      lbl.color           = tintCss;
      lbl.backgroundColor = false;
      lbl.padding         = 0;
      lbl.textHeight      = 5.0;
      lbl.fontFace        = "JetBrains Mono, ui-monospace, monospace";
      lbl.fontWeight      = "500";
      lbl.strokeWidth     = 0.6;
      lbl.strokeColor     = "#020617";
      lbl.material.depthWrite  = false;
      lbl.material.transparent = true;
      lbl.renderOrder     = 20;
      lbl.position.set(0, -10, 0);
      lbl.userData = { kind: "projectLabel" };
      group.add(lbl);

      // -- Files: spherical-Fibonacci orbit within R_FILES ------------
      var n = files.length;
      for (var i = 0; i < n; i++) {
        var phi   = Math.acos(1 - 2 * (i + 0.5) / Math.max(1, n));
        var theta = Math.PI * (1 + Math.sqrt(5)) * i;
        var fx = R_FILES * Math.sin(phi) * Math.cos(theta);
        var fy = R_FILES * Math.sin(phi) * Math.sin(theta);
        var fz = R_FILES * Math.cos(phi);

        var filePath = files[i].path || "file_" + i;
        var iconKey  = pickIconKey(filePath);

        // Invisible sprite scaffold for icon overlay
        var sprite = new THREE.Sprite(
          new THREE.SpriteMaterial({ visible: false, depthWrite: false })
        );
        sprite.position.set(fx, fy, fz);
        sprite.scale.setScalar(1);
        sprite.userData = {
          type: "file", path: filePath,
          projectId: manifest.id, fileIndex: i,
        };
        filesContainer.add(sprite);
        this._registerIconOverlay(sprite, iconKey, 32);

        // Edge from project center to file
        var lineGeom = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(0, 0, 0),
          new THREE.Vector3(fx, fy, fz),
        ]);
        var lineMat = new THREE.LineBasicMaterial({
          color: tint, transparent: true, opacity: 0.18,
        });
        edgesContainer.add(new THREE.Line(lineGeom, lineMat));

        // File label (textHeight = 2.4, bright white #f1f5f9)
        var fLabel = new SpriteText(basename(filePath));
        fLabel.color           = "#f1f5f9";
        fLabel.backgroundColor = false;
        fLabel.padding         = 0;
        fLabel.textHeight      = 2.4;
        fLabel.fontFace        = "JetBrains Mono, ui-monospace, monospace";
        fLabel.fontWeight      = "400";
        fLabel.strokeWidth     = 0.4;
        fLabel.strokeColor     = "#020617";
        fLabel.material.depthWrite  = false;
        fLabel.material.transparent = true;
        fLabel.renderOrder     = 19;
        fLabel.position.set(fx, fy - 4, fz);
        fLabel.userData = { kind: "fileLabel" };
        filesContainer.add(fLabel);
      }

      return group;
    }

    // =================================================================
    // Camera navigation
    // =================================================================
    flyToProject(projectId) {
      var group = this.projectGroups.get(projectId);
      if (!group) return;

      this.focusedProjectId = projectId;
      var target = group.position.clone();
      var offset = new THREE.Vector3(0, 25, 110);
      var camDest = target.clone().add(offset);

      this._tweenCamera(camDest, 900, target);
      this._pulseHalo(projectId);
      this._updateStatusBar();
      this._updateBreadcrumb();
    }

    flyToOverview() {
      this.focusedProjectId = null;
      this._tweenCamera(
        HOME_POS,
        900,
        new THREE.Vector3(0, 0, 0)
      );
      this._updateStatusBar();
      this._updateBreadcrumb();
    }

    // =================================================================
    // Distance-based LOD -- sub-group toggling
    // =================================================================
    _updateProjectDetail() {
      var camPos = this.camera.position;
      for (var _i = 0, _a = Array.from(this.projectGroups.values()); _i < _a.length; _i++) {
        var group = _a[_i];
        var d = camPos.distanceTo(group.position);

        for (var ci = 0; ci < group.children.length; ci++) {
          var child = group.children[ci];
          var ud = child.userData;
          if (!ud) continue;

          if (ud.kind === "filesContainer") {
            if (d < LOD_FULL) {
              child.visible = true;
              // Show all children
              for (var fi = 0; fi < child.children.length; fi++) {
                child.children[fi].visible = true;
              }
            } else if (d < LOD_MEDIUM) {
              child.visible = true;
              var fileIdx = 0;
              for (var fi2 = 0; fi2 < child.children.length; fi2++) {
                var fc = child.children[fi2];
                if (fc.userData && fc.userData.type === "file") {
                  fc.visible = fileIdx < MEDIUM_FILE_CAP;
                  fileIdx++;
                } else if (fc.userData && fc.userData.kind === "fileLabel") {
                  fc.visible = false;
                }
              }
            } else {
              child.visible = false;
            }
          } else if (ud.kind === "edgesContainer") {
            child.visible = d < LOD_FULL;
          }
          // project_icon, project_halo, projectLabel -- always visible
        }
      }
    }

    // =================================================================
    // Label opacity fading -- per-frame distance-based
    //
    // Ranges (spec):
    //   vaultStarLabel  60-1200
    //   clusterLabel   200-1400
    //   projectLabel    80-700
    //   fileLabel       25-90
    // =================================================================
    _updateLabelOpacities() {
      var camPos = this.camera.position;
      var tmpVec = new THREE.Vector3();

      // Vault star label
      if (this.vaultStarGroup) {
        for (var vi = 0; vi < this.vaultStarGroup.children.length; vi++) {
          var vc = this.vaultStarGroup.children[vi];
          if (!vc.isSprite || !vc.material || !vc.userData) continue;
          if (vc.userData.kind === "vaultStarLabel") {
            vc.getWorldPosition(tmpVec);
            var d = camPos.distanceTo(tmpVec);
            vc.material.opacity = THREE.MathUtils.clamp(
              1 - (d - 60) / (1200 - 60), 0, 1
            );
          }
        }
      }

      // Cluster labels
      for (var cli = 0; cli < this.clusterGroup.children.length; cli++) {
        var cl = this.clusterGroup.children[cli];
        if (!cl.isSprite || !cl.material || !cl.userData) continue;
        if (cl.userData.kind === "clusterLabel") {
          cl.getWorldPosition(tmpVec);
          var dCl = camPos.distanceTo(tmpVec);
          cl.material.opacity = THREE.MathUtils.clamp(
            1 - (dCl - 200) / (1400 - 200), 0, 1
          );
        }
      }

      // Project + file labels (traverse into sub-groups)
      for (var _i = 0, _a = Array.from(this.projectGroups.entries()); _i < _a.length; _i++) {
        var entry = _a[_i];
        var group = entry[1];
        var groupDist = camPos.distanceTo(group.position);

        // Recursive traverse for labels inside group and its sub-groups
        (function traverse(obj) {
          if (obj.isSprite && obj.material && obj.material.transparent && obj.userData && obj.userData.kind) {
            obj.getWorldPosition(tmpVec);
            var d2 = camPos.distanceTo(tmpVec);

            if (obj.userData.kind === "projectLabel") {
              obj.material.opacity = THREE.MathUtils.clamp(
                1 - (d2 - 80) / (700 - 80), 0, 1
              );
            } else if (obj.userData.kind === "fileLabel") {
              var op = THREE.MathUtils.clamp(1 - (d2 - 25) / (90 - 25), 0, 1);
              obj.material.opacity = op;
              obj.visible = op > 0.01 && groupDist < LOD_FULL;
            }
          }
          if (obj.children) {
            for (var chi = 0; chi < obj.children.length; chi++) {
              traverse(obj.children[chi]);
            }
          }
        })(group);
      }
    }

    // =================================================================
    // Vault Star halo pulse (called every frame)
    // =================================================================
    _updateVaultStarPulse() {
      if (!this._vaultStarHalo) return;
      var t = performance.now() * 0.001;
      this._vaultStarHalo.material.opacity = 0.2 + 0.08 * Math.sin(t * 1.5);
      var scale = 40 + 4 * Math.sin(t * 1.2);
      this._vaultStarHalo.scale.set(scale, scale, 1);
    }

    // =================================================================
    // Cross-repo arcs
    // =================================================================
    drawCrossRepoArc(fromId, toId, durationMs) {
      var gA = this.projectGroups.get(fromId);
      var gB = this.projectGroups.get(toId);
      if (!gA || !gB) return;
      var a = gA.position.clone();
      var b = gB.position.clone();
      var mid = a.clone().lerp(b, 0.5).multiplyScalar(1.18);
      var curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      var geom = new THREE.TubeGeometry(curve, 24, 0.18, 6, false);
      var mat = new THREE.MeshBasicMaterial({ color: 0xa78bfa, transparent: true, opacity: 0.9 });
      var arc = new THREE.Mesh(geom, mat);
      this.arcGroup.add(arc);
      var dur = durationMs || 1400;
      var start = performance.now();
      var disposed = this._disposed;
      var arcGroup = this.arcGroup;
      var tick = function () {
        if (disposed) return;
        var t = (performance.now() - start) / dur;
        if (t >= 1) {
          arcGroup.remove(arc);
          geom.dispose(); mat.dispose();
          return;
        }
        mat.opacity = 0.9 * (1 - t);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }

    // =================================================================
    // Dispose
    // =================================================================
    dispose() {
      this._disposed = true;
      cancelAnimationFrame(this._raf);
      window.removeEventListener("resize", this._onResize);
      document.removeEventListener("keydown", this._onKeyDown);
      this.renderer.domElement.removeEventListener("click", this._onClick);
      if (this.controls) { this.controls.dispose(); this.controls = null; }
      for (var _i = 0, _a = Array.from(this.projectGroups.values()); _i < _a.length; _i++) {
        disposeGroup(_a[_i]);
      }
      if (this.vaultStarGroup) disposeGroup(this.vaultStarGroup);
      this.arcGroup.children.forEach(function (c) {
        if (c.isMesh) { c.geometry.dispose(); c.material.dispose(); }
      });
      this.renderer.dispose();
      if (this.renderer.domElement.parentNode) {
        this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
      }
      if (this.overlayEl && this.overlayEl.parentNode) {
        this.overlayEl.parentNode.removeChild(this.overlayEl);
      }
      this.iconElMap.clear();
    }

    // =================================================================
    // Starfield
    // =================================================================
    _addStarfield() {
      var tints = [
        [1, 1, 1], [0.85, 0.92, 1], [0.96, 0.96, 0.78],
        [0.65, 0.55, 0.98], [0.37, 0.92, 0.83], [0.13, 0.83, 0.93], [1, 0.9, 0.55],
      ];
      var dpr = window.devicePixelRatio || 1;
      var shells = [
        { count: 2400, rMin: 1800, rMax: 2400, size: 3.5 * dpr },
        { count: 800,  rMin: 1000, rMax: 1600, size: 5   * dpr },
        { count: 200,  rMin: 600,  rMax: 900,  size: 8   * dpr },
      ];
      for (var si = 0; si < shells.length; si++) {
        var s = shells[si];
        var positions = new Float32Array(s.count * 3);
        var colors = new Float32Array(s.count * 3);
        for (var i = 0; i < s.count; i++) {
          var u = Math.random(), v = Math.random();
          var theta = 2 * Math.PI * u, phi = Math.acos(2 * v - 1);
          var r = s.rMin + Math.random() * (s.rMax - s.rMin);
          positions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
          positions[i * 3 + 1] = r * Math.cos(phi);
          positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
          var t = tints[Math.floor(Math.random() * tints.length)];
          colors[i * 3]     = t[0]; colors[i * 3 + 1] = t[1]; colors[i * 3 + 2] = t[2];
        }
        var geom = new THREE.BufferGeometry();
        geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
        var mat = new THREE.PointsMaterial({
          size: s.size, vertexColors: true, transparent: true, opacity: 0.85,
          blending: THREE.AdditiveBlending, sizeAttenuation: true, depthWrite: false,
        });
        this.scene.add(new THREE.Points(geom, mat));
      }
    }

    // =================================================================
    // Camera tween
    // =================================================================
    _tweenCamera(target, ms, lookAt) {
      var aim = lookAt || new THREE.Vector3(0, 0, 0);
      var start = this.camera.position.clone();
      var startTgt = this.controls
        ? this.controls.target.clone()
        : new THREE.Vector3(0, 0, 0);
      var t0 = performance.now();
      var self = this;
      var tick = function () {
        if (self._disposed) return;
        var t = Math.min(1, (performance.now() - t0) / ms);
        var e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        self.camera.position.set(
          start.x + (target.x - start.x) * e,
          start.y + (target.y - start.y) * e,
          start.z + (target.z - start.z) * e
        );
        if (self.controls) {
          self.controls.target.set(
            startTgt.x + (aim.x - startTgt.x) * e,
            startTgt.y + (aim.y - startTgt.y) * e,
            startTgt.z + (aim.z - startTgt.z) * e
          );
          self.controls.update();
        } else {
          self.camera.lookAt(aim.x, aim.y, aim.z);
        }
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }

    _installResize() {
      var self = this;
      this._onResize = function () {
        if (!self.host || !self.host.clientWidth) return;
        var w = self.host.clientWidth, h = self.host.clientHeight;
        self.camera.aspect = w / Math.max(1, h);
        self.camera.updateProjectionMatrix();
        self.renderer.setSize(w, h, false);
      };
      window.addEventListener("resize", this._onResize);
      setTimeout(this._onResize, 50);
    }

    // =================================================================
    // Click interaction
    // =================================================================
    _installInteraction() {
      var self = this;
      this._onClick = function (ev) {
        var rect = self.renderer.domElement.getBoundingClientRect();
        var ndc = new THREE.Vector2(
          ((ev.clientX - rect.left) / rect.width) * 2 - 1,
          -((ev.clientY - rect.top) / rect.height) * 2 + 1
        );
        var ray = new THREE.Raycaster();
        ray.setFromCamera(ndc, self.camera);
        var hits = ray.intersectObjects(self._clickTargets, false);
        for (var hi = 0; hi < hits.length; hi++) {
          var ud = hits[hi].object && hits[hi].object.userData;
          if (ud && ud.projectId) {
            self.flyToProject(ud.projectId);
            return;
          }
        }
      };
      this.renderer.domElement.addEventListener("click", this._onClick);
    }

    // =================================================================
    // Halo pulse on fly-to
    // =================================================================
    _pulseHalo(projectId) {
      var group = this.projectGroups.get(projectId);
      if (!group) return;
      var halo = null;
      for (var ci = 0; ci < group.children.length; ci++) {
        if (group.children[ci].userData && group.children[ci].userData.type === "project_halo") {
          halo = group.children[ci]; break;
        }
      }
      if (!halo) return;
      var baseScaleX = halo.scale.x;
      var baseScaleY = halo.scale.y;
      var t0 = performance.now();
      var disposed = this._disposed;
      var tick = function () {
        if (disposed || !halo.parent) return;
        var t = (performance.now() - t0) / 700;
        if (t >= 1) {
          halo.scale.set(baseScaleX, baseScaleY, 1);
          return;
        }
        var wave = 1 + Math.sin(t * Math.PI) * 0.6;
        halo.scale.set(baseScaleX * wave, baseScaleY * wave, 1);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }

    // =================================================================
    // Status bar
    // =================================================================
    _updateStatusBar() {
      try {
        var inVault = (typeof currentViewMode !== "undefined" && currentViewMode === "vault");
        var sn = document.getElementById("status-nodes");
        var sv = document.getElementById("status-view");
        if (inVault && sn) {
          var repoCount = this.projectGroups.size;
          var totalFiles = 0;
          for (var _m of this.projectMeta.values()) totalFiles += _m.fileCount || 0;
          if (this.focusedProjectId) {
            var meta = this.projectMeta.get(this.focusedProjectId);
            var name = (meta && meta.name) || this.focusedProjectId.replace(/^[a-z]+:/, "");
            sn.textContent = "REPOS: " + repoCount + " · NODES: " + totalFiles + " · ACTIVE: " + name;
          } else {
            sn.textContent = "REPOS: " + repoCount + " · NODES: " + totalFiles + " · ACTIVE: overview";
          }
        }
        if (inVault && sv) {
          sv.textContent = "VIEW: VAULT";
        }
      } catch (_) {}
    }

    // =================================================================
    // Breadcrumb
    // =================================================================
    _ensureBreadcrumb() {
      var bc = document.getElementById("galaxy-breadcrumb");
      if (bc) return bc;
      var wrap = document.getElementById("canvas-wrap");
      if (!wrap) return null;
      bc = document.createElement("div");
      bc.id = "galaxy-breadcrumb";
      bc.style.cssText =
        "position:absolute;top:14px;left:18px;z-index:30;display:none;" +
        "background:rgba(2,6,23,0.78);border:1px solid rgba(167,139,250,0.45);" +
        "color:#e9d5ff;font-family:'JetBrains Mono',monospace;font-size:11px;" +
        "padding:5px 12px;border-radius:14px;backdrop-filter:blur(8px);" +
        "box-shadow:0 4px 18px rgba(124,58,237,0.25);";
      wrap.appendChild(bc);
      return bc;
    }

    _updateBreadcrumb() {
      var bc = this._ensureBreadcrumb();
      if (!bc) return;
      var inVault = (typeof currentViewMode !== "undefined" && currentViewMode === "vault");
      if (!inVault) { bc.style.display = "none"; return; }
      bc.style.display = "block";
      if (this.focusedProjectId) {
        var meta = this.projectMeta.get(this.focusedProjectId);
        var name = (meta && meta.name) || this.focusedProjectId.replace(/^[a-z]+:/, "");
        var safe = String(name).replace(/[&<>"']/g, function (c) {
          return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];
        });
        bc.innerHTML =
          '<span style="cursor:pointer;color:#c4b5fd;" onclick="window.aetherGalaxyApp.flyToOverview()">Vault</span>' +
          ' <span style="opacity:0.4;">›</span> ' +
          '<span style="color:#fff;">' + safe + '</span>';
      } else {
        bc.innerHTML = '<span style="color:#c4b5fd;">Vault</span>';
      }
    }

    // =================================================================
    // Render loop
    // =================================================================
    _loop() {
      var self = this;
      var frame = function () {
        if (self._disposed) return;
        if (self.controls) self.controls.update();
        self._updateProjectDetail();
        self._updateLabelOpacities();
        self._updateVaultStarPulse();
        self.renderer.render(self.scene, self.camera);
        self._syncIconOverlay();
        self._raf = requestAnimationFrame(frame);
      };
      this._raf = requestAnimationFrame(frame);
    }

    // =================================================================
    // Icon overlay sync
    // =================================================================
    _syncIconOverlay() {
      if (!this.overlayEl || this.iconElMap.size === 0) return;
      var r = this.overlayEl.getBoundingClientRect();
      var W = r.width, H = r.height;
      if (W === 0 || H === 0) return;
      for (var _e of this.iconElMap.values()) {
        var sprite = _e.sprite, img = _e.img;
        if (!sprite || !img) continue;
        var visible = sprite.visible;
        var p = sprite.parent;
        while (visible && p) { if (!p.visible) visible = false; p = p.parent; }
        if (!visible) { img.style.display = "none"; continue; }
        sprite.getWorldPosition(this._projVec);
        this._projVec.project(this.camera);
        if (this._projVec.z > 1 || this._projVec.z < -1) {
          img.style.display = "none";
          continue;
        }
        var sx = (this._projVec.x * 0.5 + 0.5) * W;
        var sy = (-this._projVec.y * 0.5 + 0.5) * H;
        var depth = (1 - this._projVec.z) * 0.5;
        var scale = 0.4 + depth * 0.8;
        img.style.display = "";
        img.style.transform =
          "translate(-50%, -50%) translate(" + sx + "px, " + sy + "px) " +
          "scale(" + scale.toFixed(3) + ")";
      }
    }

    _registerIconOverlay(sprite, iconKey, px) {
      if (!sprite || !this.overlayEl) return;
      var icons = window.AETHER_VAULT_ICONS;
      if (!icons) return;
      var fallback = icons.files[iconKey] ? iconKey : "doc";
      var url = icons.dataUrls[fallback];
      if (!url) return;
      var img = document.createElement("img");
      img.draggable = false;
      img.alt = iconKey || "";
      img.src = url;
      img.style.cssText =
        "position:absolute;top:0;left:0;width:" + px + "px;height:" + px + "px;" +
        "transform-origin:50% 50%;will-change:transform;display:none;" +
        "user-select:none;-webkit-user-drag:none;pointer-events:none;" +
        "image-rendering:crisp-edges;image-rendering:-webkit-optimize-contrast;";
      this.overlayEl.appendChild(img);
      this.iconElMap.set(sprite.uuid, { sprite: sprite, img: img });
    }

    _gcOverlayIcons() {
      for (var _e of this.iconElMap.entries()) {
        var uuid = _e[0], entry = _e[1];
        var sprite = entry.sprite;
        var p = sprite ? sprite.parent : null;
        var attached = false;
        while (p) { if (p === this.scene) { attached = true; break; } p = p.parent; }
        if (!attached) {
          if (entry.img && entry.img.parentNode) entry.img.parentNode.removeChild(entry.img);
          this.iconElMap.delete(uuid);
        }
      }
    }

    // =================================================================
    // Universe-wide search
    // =================================================================
    _ensureQueryBar() {
      if (this._qBar) return this._qBar;
      var self = this;
      var wrap = document.createElement("div");
      wrap.id = "galaxy-querybar";
      wrap.style.cssText =
        "position:absolute;top:14px;right:14px;z-index:25;display:none;" +
        "min-width:280px;max-width:380px;font-family:'JetBrains Mono',monospace;";
      var input = document.createElement("input");
      input.type = "text";
      input.placeholder = "Search the universe…";
      input.style.cssText =
        "width:100%;box-sizing:border-box;padding:7px 11px;font-size:12px;" +
        "background:rgba(2,6,23,0.82);border:1px solid rgba(94,234,212,0.45);" +
        "color:#e9d5ff;border-radius:14px;outline:none;backdrop-filter:blur(8px);";
      var panel = document.createElement("div");
      panel.style.cssText =
        "margin-top:6px;max-height:380px;overflow-y:auto;display:none;" +
        "background:rgba(2,6,23,0.92);border:1px solid rgba(94,234,212,0.35);" +
        "border-radius:10px;padding:6px;backdrop-filter:blur(8px);" +
        "box-shadow:0 8px 32px rgba(0,0,0,0.65);";
      wrap.appendChild(input);
      wrap.appendChild(panel);
      this.host.appendChild(wrap);
      this._qBar = { wrap: wrap, input: input, panel: panel };

      var pending = null;
      input.addEventListener("input", function () {
        if (pending) clearTimeout(pending);
        pending = setTimeout(function () { self._runQuery(input.value); }, 110);
      });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { input.value = ""; self._renderQueryHits([]); input.blur(); }
      });
      return this._qBar;
    }

    _showQueryBar(visible) {
      var q = this._ensureQueryBar();
      q.wrap.style.display = visible ? "block" : "none";
      if (!visible) { q.panel.style.display = "none"; }
    }

    async _runQuery(text) {
      var q = (text || "").trim().toLowerCase();
      if (!q) { this._renderQueryHits([]); return; }
      if (!this.projectMeta) { this._renderQueryHits([]); return; }

      var hits = [];
      // Pass 1: project name + path match
      for (var m of this.projectMeta.values()) {
        var name = String(m.name || "").toLowerCase();
        var path = String(m.path || "").toLowerCase();
        if (name.includes(q)) {
          hits.push({ kind: "project", projectId: m.id, name: m.name, path: m.path, score: 1.0 });
        } else if (path && path.includes(q)) {
          hits.push({ kind: "project", projectId: m.id, name: m.name, path: m.path, score: 0.6 });
        }
      }

      // Pass 2: file path match -- traverse into sub-groups
      for (var _e of this.projectGroups.entries()) {
        var id = _e[0], group = _e[1];
        var meta = this.projectMeta.get(id);
        group.traverse(function (child) {
          var ud = child.userData;
          if (ud && ud.type === "file" && ud.path) {
            if (String(ud.path).toLowerCase().includes(q)) {
              hits.push({
                kind: "file",
                projectId: id,
                projectName: (meta && meta.name) || id,
                path: ud.path,
                score: q.length / Math.max(1, ud.path.length),
              });
            }
          }
        });
      }

      hits.sort(function (a, b) { return b.score - a.score; });
      var top = hits.slice(0, 25);

      // Auto-fly if exactly one project hit and zero file hits
      var projectHits = top.filter(function (h) { return h.kind === "project"; });
      var fileHits = top.filter(function (h) { return h.kind === "file"; });
      if (projectHits.length === 1 && fileHits.length === 0 && q.length >= 3) {
        this._renderQueryHits([]);
        if (this._qBar) this._qBar.input.value = "";
        this.flyToProject(projectHits[0].projectId);
        return;
      }
      this._renderQueryHits(top);
    }

    _renderQueryHits(hits) {
      var self = this;
      var q = this._ensureQueryBar();
      var panel = q.panel;
      panel.innerHTML = "";
      if (!hits.length) { panel.style.display = "none"; return; }
      var escape = function (s) {
        return String(s).replace(/[&<>"']/g, function (c) {
          return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];
        });
      };
      for (var hi = 0; hi < hits.length; hi++) {
        var h = hits[hi];
        var row = document.createElement("div");
        row.style.cssText =
          "padding:6px 8px;cursor:pointer;border-radius:6px;font-size:11px;" +
          "color:#e2e8f0;display:flex;align-items:center;gap:8px;";
        row.onmouseenter = function () { this.style.background = "rgba(94,234,212,0.12)"; };
        row.onmouseleave = function () { this.style.background = "transparent"; };
        if (h.kind === "project") {
          row.innerHTML =
            '<span style="color:#5eead4;flex-shrink:0;">▣</span>' +
            '<span style="font-weight:600;color:#e9d5ff;">' + escape(h.name) + '</span>' +
            (h.path ? '<span style="opacity:0.5;font-size:10px;">' + escape(h.path) + '</span>' : '');
          row.onclick = (function (pid) {
            return function () {
              panel.style.display = "none";
              q.input.value = "";
              self.flyToProject(pid);
            };
          })(h.projectId);
        } else {
          row.innerHTML =
            '<span style="color:#fbbf24;flex-shrink:0;">▸</span>' +
            '<span style="color:#cbd5e1;">' + escape(h.path) + '</span>' +
            '<span style="opacity:0.55;margin-left:auto;font-size:10px;">' + escape(h.projectName) + '</span>';
          row.onclick = (function (pid) {
            return function () {
              panel.style.display = "none";
              q.input.value = "";
              self.flyToProject(pid);
            };
          })(h.projectId);
        }
        panel.appendChild(row);
      }
      panel.style.display = "block";
    }
  }

  // ===================================================================
  // CrossRepoQuery -- auth-checked fan-out, IPC-backed
  // ===================================================================
  class CrossRepoQuery {
    constructor(opts) {
      this.scene = opts && opts.scene;
      this.perRepoK = (opts && opts.perRepoK) || 10;
      this.finalK = (opts && opts.finalK) || 25;
      this.maxParallel = (opts && opts.maxParallel) || 6;
    }
    async query(req) {
      var t0 = performance.now();
      var text = req.text || "";
      var embeddingArr = req.embedding || await ipc.vector.embed(text);
      var embedding = embeddingArr instanceof Float32Array
        ? embeddingArr : Float32Array.from(embeddingArr || []);
      var candidateRepos = req.repoIds || await ipc.vector.listRepos();
      var allowed = [];
      var skipped = [];
      for (var ri = 0; ri < candidateRepos.length; ri++) {
        var id = candidateRepos[ri];
        var ok = await ipc.auth.canRead(req.agentId, id);
        if (!ok) { skipped.push({ id: id, reason: "unauthorized" }); continue; }
        allowed.push(id);
      }
      var perRepo = await mapWithConcurrency(allowed, this.maxParallel, async function (rid) {
        try {
          var hits = await ipc.vector.searchRepo(rid, Array.from(embedding), 10);
          return { repoId: rid, hits: hits || [] };
        } catch (_) {
          skipped.push({ id: rid, reason: "unavailable" });
          return { repoId: rid, hits: [] };
        }
      });
      var merged = mergeAndRank(perRepo, this.finalK);
      if (this.scene && req.originRepoId) {
        var seen = new Set();
        for (var mi = 0; mi < merged.length; mi++) {
          var h = merged[mi];
          if (h.repoId === req.originRepoId || seen.has(h.repoId)) continue;
          seen.add(h.repoId);
          this.scene.drawCrossRepoArc(req.originRepoId, h.repoId);
        }
      }
      ipc.auth.audit({
        agentId: req.agentId, action: "cross_repo_query",
        repos: allowed, skipped: skipped, hitCount: merged.length,
      });
      return { hits: merged, searchedRepos: allowed, skippedRepos: skipped, elapsedMs: performance.now() - t0 };
    }
    async fetchSnippet(agentId, hit, maxBytes) {
      var ok = await ipc.auth.canRead(agentId, hit.repoId);
      if (!ok) return null;
      return ipc.vector.readFileSlice(hit.repoId, hit.fileId, maxBytes || 4096);
    }
  }

  function mergeAndRank(perRepo, finalK) {
    var out = [];
    for (var ri = 0; ri < perRepo.length; ri++) {
      var repoId = perRepo[ri].repoId, hits = perRepo[ri].hits;
      if (!hits.length) continue;
      var scores = hits.map(function (h) { return h.score; });
      var min = Math.min.apply(null, scores);
      var max = Math.max.apply(null, scores);
      var range = (max - min) || 1;
      for (var hi = 0; hi < hits.length; hi++) {
        var h = hits[hi];
        out.push({
          repoId: repoId, fileId: h.fileId, path: h.path,
          score: (h.score - min) / range,
          snippetPreview: h.snippetPreview,
        });
      }
    }
    out.sort(function (a, b) { return b.score - a.score; });
    return out.slice(0, finalK);
  }

  async function mapWithConcurrency(items, limit, fn) {
    var results = new Array(items.length);
    var cursor = 0;
    async function worker() {
      while (true) {
        var i = cursor++;
        if (i >= items.length) return;
        results[i] = await fn(items[i]);
      }
    }
    var lanes = Array.from({ length: Math.min(limit, items.length) }, function () { return worker(); });
    await Promise.all(lanes);
    return results;
  }

  // ===================================================================
  // App: mount surface + view-mode hook
  // ===================================================================
  var scene = null;
  var crossRepo = null;
  var host = null;

  function ensureHost() {
    host = document.getElementById("galaxyHost");
    if (host) return host;
    var wrap = document.getElementById("canvas-wrap");
    if (!wrap) return null;
    host = document.createElement("div");
    host.id = "galaxyHost";
    host.style.cssText = "position:absolute;inset:0;z-index:11;display:none;background:#000;";
    wrap.appendChild(host);
    return host;
  }

  function readVaultEntries() {
    try {
      var cs = typeof CS !== "undefined" ? CS : null;
      if (!cs || !Array.isArray(cs.nodes)) return [];
      return cs.nodes.filter(function (n) { return !n.isRoot && (n.path || n.name); });
    } catch (_) { return []; }
  }

  function vaultManifest(entries) {
    if (!entries || entries.length === 0) return null;
    return {
      id: "local:vault",
      name: "current vault",
      path: null,
      fileCount: entries.length,
      builtAt: Date.now(),
      lastTouchedAt: Date.now(),
    };
  }

  var _lastVaultFp = "";

  async function init() {
    var h = ensureHost();
    if (!h) return false;
    if (scene) return true;
    scene = new VaultSceneManager(h);
    crossRepo = new CrossRepoQuery({ scene: scene });
    try {
      var manifests = await ipc.repo.manifests();
      var seeded = manifests.length > 0 ? manifests : seedSyntheticManifests();
      var vaultNodes = readVaultEntries();
      var vm = vaultManifest(vaultNodes);
      if (vm) {
        SYNTH_COUNTS[vm.id] = vm.fileCount;
        seeded.push(vm);
      }
      _lastVaultFp = String(vaultNodes.length);
      await scene.buildVault(seeded);
    } catch (e) {
      console.warn("[vault3d] manifest fetch failed, using synthetic seed:", e);
      await scene.buildVault(seedSyntheticManifests());
    }
    return true;
  }

  async function updateVaultEntries() {
    if (!scene) return;
    var entries = readVaultEntries();
    var fp = String(entries.length);
    if (fp === _lastVaultFp) return;
    _lastVaultFp = fp;
    try {
      var manifests = await ipc.repo.manifests();
      var seeded = manifests.length > 0 ? manifests : seedSyntheticManifests();
      var vm = vaultManifest(entries);
      if (vm) {
        SYNTH_COUNTS[vm.id] = vm.fileCount;
        seeded.push(vm);
      }
      await scene.buildVault(seeded);
    } catch (_) {}
  }

  function seedSyntheticManifests() {
    var now = Date.now();
    var D = 24 * 60 * 60 * 1000;
    var seed = [
      { id: "demo:aether-cloud-trading-engine", name: "aether-cloud-trading-engine", path: "~/code/trading", fileCount: 42, lastTouchedAt: now - 0.2 * D },
      { id: "demo:aether-cloud-vault",          name: "aether-cloud-vault",          path: "~/code/vault",   fileCount: 28, lastTouchedAt: now - 1.1 * D },
      { id: "demo:patents-research",            name: "patents-research",            path: "~/docs/patents", fileCount: 14, lastTouchedAt: now - 2.6 * D },
      { id: "demo:claude-code-mirror",          name: "claude-code-mirror",          path: "~/code/cc",      fileCount: 31, lastTouchedAt: now - 4.0 * D },
      { id: "demo:opensec-credentials",         name: "opensec-credentials",         path: "~/sec/creds",    fileCount: 9,  lastTouchedAt: now - 6.5 * D },
      { id: "demo:security-audit-2026",         name: "security-audit-2026",         path: "~/sec/audit",    fileCount: 18, lastTouchedAt: now - 0.5 * D },
      { id: "demo:llm-models-vault",            name: "llm-models-vault",            path: "~/models",       fileCount: 6,  lastTouchedAt: now - 11 * D },
      { id: "demo:strategy-backtests",          name: "strategy-backtests",          path: "~/code/bt",      fileCount: 22, lastTouchedAt: now - 0.05 * D },
      { id: "demo:doc-archive",                 name: "doc-archive",                 path: "~/docs/old",     fileCount: 5,  lastTouchedAt: now - 26 * D },
      { id: "demo:desktop-screenshots",         name: "desktop-screenshots",         path: "~/Desktop/screens", fileCount: 8, lastTouchedAt: now - 0.8 * D },
      { id: "demo:downloads-assets",            name: "downloads-assets",            path: "~/Downloads/assets", fileCount: 12, lastTouchedAt: now - 1.5 * D },
    ];
    for (var si = 0; si < seed.length; si++) {
      seed[si].builtAt = seed[si].lastTouchedAt;
      SYNTH_COUNTS[seed[si].id] = seed[si].fileCount;
    }
    return seed;
  }

  function show() {
    if (!host) ensureHost();
    if (!host) return;
    host.style.display = "block";
    if (scene) {
      if (scene._onResize) scene._onResize();
      scene._updateBreadcrumb();
      scene._updateStatusBar();
      scene._showQueryBar(true);
    }
  }
  function hide() {
    if (host) host.style.display = "none";
    var bc = document.getElementById("galaxy-breadcrumb");
    if (bc) bc.style.display = "none";
    if (scene) scene._showQueryBar(false);
  }

  function isGalaxyMode() {
    try { return currentViewMode === "vault"; } catch (_) { return false; }
  }

  function installViewModeHook() {
    if (typeof window.switchViewMode !== "function" || window.switchViewMode.__galaxyWrapped) return;
    var orig = window.switchViewMode;
    var wrapped = function (mode) {
      var r = orig.apply(this, arguments);
      try {
        if (mode === "vault") {
          init().then(function () { show(); });
        } else {
          hide();
        }
      } catch (e) { console.warn("[vault3d] mode hook failed:", e); }
      return r;
    };
    wrapped.__galaxyWrapped = true;
    window.switchViewMode = wrapped;
  }

  window.aetherGalaxyApp = {
    __installed: true,
    init: init, show: show, hide: hide, isGalaxyMode: isGalaxyMode, updateVaultEntries: updateVaultEntries,
    flyToProject: function (id) { if (scene) scene.flyToProject(id); },
    flyToOverview: function () { if (scene) scene.flyToOverview(); },
    drawArc: function (a, b, dur) { if (scene) scene.drawCrossRepoArc(a, b, dur); },
    query: function (req) { return crossRepo && crossRepo.query(req); },
    fetchSnippet: function (agentId, hit, max) { return crossRepo && crossRepo.fetchSnippet(agentId, hit, max); },
    agentTool: {
      name: "crossRepoLookup",
      description:
        "Search across all repos the agent is authorized to read. " +
        "Returns ranked file hits {repoId, fileId, path, score}. Use fetchSnippet on " +
        "individual hits to read file content (auth re-checked).",
      handler: function (args) {
        return crossRepo && crossRepo.query({
          text: args.query, agentId: args.agentId || "default",
          originRepoId: args.originRepoId, repoIds: args.repoIds,
        });
      },
    },
  };

  function start() {
    installViewModeHook();
    try {
      if (typeof currentViewMode !== "undefined" && currentViewMode === "vault") {
        init().then(function () { show(); });
      }
    } catch (_) {}
    setInterval(function () {
      try {
        if (typeof currentViewMode !== "undefined" && currentViewMode === "vault") {
          updateVaultEntries();
        }
      } catch (_) {}
    }, 2000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
