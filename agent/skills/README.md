# AetherCloud Bundled Skills

Skills are behavioral instruction documents that AetherCloud's Claude agents (Forge, Drift) can load on demand to follow structured workflows. They are shipped with every AetherCloud install — bundled into the packaged app via `extraResources` — so users get them without any network fetch.

## What a Skill Is

A skill is a directory containing a `SKILL.md` file with YAML frontmatter and markdown instructions. The skill's content is injected into the agent's system context when a user (or the agent itself) invokes it by name.

```
skills/
  systematic-debugging/
    SKILL.md            ← required: frontmatter + instructions
    root-cause-tracing.md   ← optional: supporting reference docs
    ...
```

## Frontmatter Contract

Every `SKILL.md` must begin with a YAML frontmatter block:

```yaml
---
name: skill-name          # kebab-case, matches directory name
description: "One sentence — when to use this skill"
scope: optional           # optional: "global", "project", or omit
---
```

- `name` — must match the directory name exactly (kebab-case, no spaces)
- `description` — used by the skill loader to surface the skill in UI and logs
- `scope` — optional; omit unless the skill is context-specific

## How to Add a Skill

1. Create a new directory under `agent/skills/` using kebab-case: `agent/skills/my-skill/`
2. Add `SKILL.md` with valid frontmatter (see contract above)
3. Add any supporting `.md` reference files in the same directory
4. Run the CI check to verify: `node scripts/check-skills.js`
5. Commit and open a PR

## How Skills Are Loaded

`agent/skill-loader.js` handles discovery and loading:

- **Dev mode**: reads from `agent/skills/` relative to the loader file
- **Packaged mode**: reads from `resources/skills/` inside the installed app (`process.resourcesPath`)

Two IPC channels expose skills to renderer/agent code:
- `agent:listSkills` → `string[]` of available skill names
- `agent:loadSkill(name)` → `{ success, name, meta, content }` or `{ success: false, error }`

## User-Scope Skills

These shipped skills are **read-only** — do not edit them in place. User-specific or project-specific skills should live in the user's local Claude Code skills directory (`~/.claude/skills/`) and are not committed to this repo.

## Bundling

Skills are included in every packaged release via electron-builder `extraResources`:

```json
"extraResources": [{ "from": "../agent/skills", "to": "skills" }]
```

The CI check (`scripts/check-skills.js`) fails the build if the skills directory is missing or contains no valid `SKILL.md` files.
