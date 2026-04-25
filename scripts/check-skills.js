#!/usr/bin/env node
/**
 * CI check: verify agent/skills/ is present and contains at least one valid SKILL.md.
 * Fails with exit code 1 if the directory is missing or empty of valid skills.
 * Run: node scripts/check-skills.js
 */

const path = require('path');
const fs = require('fs');

const SKILLS_DIR = path.join(__dirname, '..', 'agent', 'skills');
const MIN_SKILLS = 1;

function run() {
  if (!fs.existsSync(SKILLS_DIR)) {
    console.error(`[check-skills] FAIL: skills directory not found: ${SKILLS_DIR}`);
    process.exit(1);
  }

  const entries = fs.readdirSync(SKILLS_DIR, { withFileTypes: true });
  const validSkills = entries.filter(e => {
    if (!e.isDirectory()) return false;
    return fs.existsSync(path.join(SKILLS_DIR, e.name, 'SKILL.md'));
  });

  if (validSkills.length < MIN_SKILLS) {
    console.error(
      `[check-skills] FAIL: expected at least ${MIN_SKILLS} skill(s) with SKILL.md, found ${validSkills.length}`
    );
    process.exit(1);
  }

  const issues = [];
  for (const skill of validSkills) {
    const content = fs.readFileSync(path.join(SKILLS_DIR, skill.name, 'SKILL.md'), 'utf8');
    const hasFrontmatter = /^---\n[\s\S]*?\n---/.test(content);
    const hasName = /^name:\s*\S/m.test(content);
    const hasDescription = /^description:\s*\S/m.test(content);
    if (!hasFrontmatter || !hasName || !hasDescription) {
      issues.push(`  - ${skill.name}: missing or incomplete frontmatter (needs name + description)`);
    }
  }

  if (issues.length > 0) {
    console.error('[check-skills] FAIL: frontmatter issues found:');
    issues.forEach(i => console.error(i));
    process.exit(1);
  }

  console.log(`[check-skills] PASS: ${validSkills.length} valid skill(s) found`);
  validSkills.forEach(s => console.log(`  - ${s.name}`));
}

run();
