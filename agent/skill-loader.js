/**
 * Skill loader for AetherCloud agents (Forge, Drift).
 *
 * Resolves the bundled skills directory in both dev and packaged modes,
 * then exposes loadSkill(name) and listSkills() via IPC to agent runtimes.
 *
 * WHY: Skills are bundled via extraResources so they're on-disk at runtime
 * without a network fetch. The path differs between Electron dev and packaged.
 */

const path = require('path');
const fs = require('fs');

function getSkillsDir() {
  // In packaged Electron, process.resourcesPath points to the Resources dir
  // where extraResources files land. In dev, resolve relative to this file.
  try {
    const { app } = require('electron');
    if (app.isPackaged) {
      return path.join(process.resourcesPath, 'skills');
    }
  } catch (_) {
    // Not running inside Electron main process — fall through to dev path
  }
  return path.join(__dirname, 'skills');
}

/**
 * Load a skill by name. Returns the SKILL.md content string or null if not found.
 * Inject the returned content into the agent's system context on demand (not eagerly).
 */
function loadSkill(name) {
  const skillFile = path.join(getSkillsDir(), name, 'SKILL.md');
  if (!fs.existsSync(skillFile)) return null;
  return fs.readFileSync(skillFile, 'utf8');
}

/**
 * Load a supporting file within a skill directory (e.g. "brainstorming/visual-companion.md").
 * Returns file content string or null if not found.
 */
function loadSkillFile(skillName, relPath) {
  const filePath = path.join(getSkillsDir(), skillName, relPath);
  if (!fs.existsSync(filePath)) return null;
  return fs.readFileSync(filePath, 'utf8');
}

/**
 * List all available skill names (directories that contain a SKILL.md).
 */
function listSkills() {
  const skillsDir = getSkillsDir();
  if (!fs.existsSync(skillsDir)) return [];
  return fs.readdirSync(skillsDir).filter(entry => {
    try {
      return fs.existsSync(path.join(skillsDir, entry, 'SKILL.md'));
    } catch (_) {
      return false;
    }
  });
}

/**
 * Parse frontmatter (name, description, scope) from a SKILL.md string.
 * Returns a plain object with the frontmatter key/value pairs.
 */
function parseSkillMeta(content) {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const meta = {};
  for (const line of match[1].split('\n')) {
    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue;
    const key = line.slice(0, colonIdx).trim();
    const value = line.slice(colonIdx + 1).trim().replace(/^"(.*)"$/, '$1');
    if (key) meta[key] = value;
  }
  return meta;
}

module.exports = { loadSkill, loadSkillFile, listSkills, parseSkillMeta, getSkillsDir };
