// Bundle entry — produces a single UMD that exposes window.THREE,
// window.ForceGraph3D, and window.SpriteText, ALL using the SAME Three.js
// instance. This is the fix for the dual-Three.js problem in the AetherCloud-L
// Electron renderer: the shipped 3d-force-graph.min.js bundles its own Three,
// and creating textures with a separate standalone three.min.js produces
// "foreign" textures that the bundled WebGLRenderer silently drops, leaving
// every Sprite.map invisible.
//
// Built with esbuild (see desktop/build/build-vault-3d.mjs). Output goes to
// vault-graph-3d/vendor/v3d-bundle.iife.js.

import * as THREE from "three";
import ForceGraph3D from "3d-force-graph";
import SpriteText from "three-spritetext";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS3DRenderer, CSS3DSprite, CSS3DObject } from "three/examples/jsm/renderers/CSS3DRenderer.js";

window.THREE = THREE;
window.ForceGraph3D = ForceGraph3D;
window.SpriteText = SpriteText;
window.OrbitControls = OrbitControls;
// Phase B v4: CSS3DRenderer + CSS3DSprite let us render icons as DOM
// <img> elements projected via CSS transforms, completely bypassing the
// WebGL texture-upload pipeline that refused to render Sprite+map in
// this Electron build (Chrome bisect proved the bug is renderer-specific).
window.CSS3DRenderer = CSS3DRenderer;
window.CSS3DSprite = CSS3DSprite;
window.CSS3DObject = CSS3DObject;
