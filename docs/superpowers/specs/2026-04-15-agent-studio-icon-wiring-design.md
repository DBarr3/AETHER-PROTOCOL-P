# Agent Studio Icon Wiring & Configuration — Design Spec

**Date:** 2026-04-15
**Status:** Approved
**Ticket:** AetherCloud-L (v0.9.5) — Agent Studio Icon Wiring & Configuration

---

## Problem

The Agent Studio "Choose an Agent" carousel shows blank dark gradient tiles instead of the pixelated agent icons. The icons exist as 20 SVG files in `agent/agents/*.svg` and each preset already has an `iconName` mapping, but the `agentLoadIcons` IPC handler reads from `path.join(__dirname, '..', 'agent', 'agents')` which resolves correctly in development but fails in the installed Electron app — `../agent/agents/` is outside the `desktop/` directory and not packaged in the asar archive. The handler returns `[]`, `allIcons` stays empty, and `_getPresetIcon()` returns `''` for every preset.

## Solution

### 1. Icon packaging fix

- Copy all 20 SVG files from `agent/agents/*.svg` into `desktop/assets/agents/`.
- Update `desktop/main.js:391` — change the icon load path from `path.join(__dirname, '..', 'agent', 'agents')` to `path.join(__dirname, 'assets', 'agents')`.
- The `package.json` `files` array already includes `assets/**/*`, so the new directory is automatically packaged in the asar.
- **Result**: `agentLoadIcons` returns all 20 icons → `allIcons` populates → carousel renders icons → editor icon picker works.

### 2. CSS enforcement — flat pixelated rendering

- Add `image-rendering: pixelated` to `.as-pcard-tile` and `.profile-icon-tile` CSS rules.
- Verify no `filter`, `box-shadow`, `backdrop-filter`, or glossy overlay is applied to icon containers.
- The SVGs already have `shape-rendering="crispEdges"` — preserve this attribute in all copied files.
- The `tileGrad` background gradient stays — it's a dark backing behind the icon, not a glass effect.

### 3. Custom agent flow

- No new code needed. The editor icon picker at line ~14727 already iterates `allIcons` and renders a selectable grid. Once `allIcons` is populated (from fix #1), the picker works.
- All 20 icons are exposed — users can select any icon for custom agents, including ones used by presets.

### 4. Forge preset verification

Current Forge definition (`AGENT_PRESETS[3]`, id: `forge`):
- **Role**: Backend Eng.
- **Prompt principles**: SOLID, contract-first, defensive programming, pre-flight checks
- **Bio**: "Builds the parts nobody sees. APIs, pipelines, services, data models. Doesn't ship until it's right."
- **Tags**: SOLID, Contract-Driven, Defensive Programming, Pre-flight Checks

**Assessment**: strictly utility-focused. No red-team, adversarial defense, security auditing, or threat-hunting language. No changes needed.

## Files changed

| File | Action |
|------|--------|
| `desktop/assets/agents/*.svg` (20 files) | **New** — copied from `agent/agents/` |
| `desktop/main.js` | Update `agentLoadIcons` path |
| `desktop/pages/dashboard.html` | Add `image-rendering: pixelated` to icon tile CSS |

## Acceptance criteria

1. Carousel displays correct pixelated icons for all 8 presets (Monarch, Vanguard, Cipher, Forge, Pixel, Canvas, Quill, Atlas).
2. Custom agent editor shows all 20 icons in the icon picker grid.
3. Icon styling is flat with no glass/gloss effects — `image-rendering: pixelated`, `shape-rendering: crispEdges`.
4. Forge agent logic remains strictly utility-focused without red-team bloat.
5. Icons render correctly in both development (`electron .`) and installed builds (`.exe`).
