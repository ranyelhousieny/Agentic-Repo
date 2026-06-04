---
description: "/new-agent <name> <type> — instantiate a new agent/workflow/command/skill/pattern from a template in Agentic-Repo. Reads the right template, fills placeholders from arguments, writes the result. Ensures conventions stay alive across new artifacts."
---

# /new-agent — Instantiate from a template

Create a new artifact (agent / workflow / slash command / skill / pattern doc) from the canonical templates in `Agentic-Repo/templates/`. Ensures every new artifact ships with the current conventions (Step 0 inline-intent, fast-mode, hook awareness, etc.) without requiring the user to remember them.

Pair with `/modernize-agent` (which audits an existing artifact against the current template).

## When the user runs `/new-agent <name> <type> [target_dir]`

Required arguments:
- `<name>` — the artifact name (e.g., `my-cool-agent`)
- `<type>` — one of: `claude-agent`, `windsurf-workflow`, `slash-command`, `skill`, `pattern-doc`

Optional argument:
- `[target_dir]` — where to write the result. If omitted, defaults are:
  - `claude-agent` → `~/.claude/commands/<name>.md` (or `~/.claude/agents/<name>.md` if the user prefers separation)
  - `windsurf-workflow` → `<project>/.windsurf/workflows/<name>.md`
  - `slash-command` → `~/.claude/commands/<name>.md`
  - `skill` → `~/.claude/skills/<name>/SKILL.md`
  - `pattern-doc` → `<project>/Knowledge/patterns/<name>.md`

### Step 1 — Resolve the template

Map `<type>` to a template path in this repo:
- `claude-agent` → `templates/claude-code-agent.md`
- `windsurf-workflow` → `templates/windsurf-workflow.md`
- `slash-command` → `templates/slash-command.md`
- `skill` → `templates/skill.md`
- `pattern-doc` → `templates/pattern-doc.md`

If the type doesn't match any of these, print `Unknown type: <type>. Valid types: claude-agent | windsurf-workflow | slash-command | skill | pattern-doc.` and exit.

### Step 2 — Read the template

Read the template file content. Identify the placeholder tokens (`{AGENT_NAME}`, `{WORKFLOW_NAME}`, `{COMMAND_NAME}`, `{SKILL_NAME}`, `{PATTERN_NAME}`, `{ROLE_DESCRIPTION}`, `{ONE_LINE_PURPOSE}`, etc.).

### Step 3 — Fill placeholders

- Replace the primary name placeholder (`{AGENT_NAME}` / `{WORKFLOW_NAME}` / etc.) with `<name>` from arguments.
- For `{ROLE_DESCRIPTION}`, `{ONE_LINE_PURPOSE}`, `{DOMAIN_DESCRIPTION}`, `{PATTERN_NAME}`-style placeholders that the user must fill manually, leave them as-is — they're TODOs for the user.
- Strip the `<!-- WHY -->` annotation comments (these are template-only documentation).
- Keep the `<!-- TODO when instantiating -->` comments (these are instructions to the user about what to fill in).

### Step 4 — Resolve target path

If the user provided `[target_dir]`, use it. Otherwise apply the default for the type.

If the target file already exists, ABORT with: `File exists: <target_path>. Refusing to overwrite. Use a different name, delete the existing file first, or run /modernize-agent <path> to update an existing artifact in-place.`

### Step 5 — Write the result

Create any missing parent directories. Write the filled template to the target path.

### Step 6 — Confirm

Print one line: `Created <type> at <target_path>. Open it to fill in the {ROLE_DESCRIPTION} / {ONE_LINE_PURPOSE} placeholders.`

## Critical rules

1. **Never overwrite.** If the target exists, abort and suggest /modernize-agent.
2. **Strip `<!-- WHY -->` annotations** but keep `<!-- TODO -->` ones. The first are template documentation; the second are instructions to the new file's author.
3. **Don't try to be clever about the role.** The user fills `{ROLE_DESCRIPTION}` themselves — the AI shouldn't guess what they wanted.
4. **Templates evolve over time.** Always read the LATEST version of the template at instantiation time. Don't cache.

## Example

```
/new-agent my-data-agent claude-agent

→ Created claude-agent at ~/.claude/commands/my-data-agent.md.
  Open it to fill in the {ROLE_DESCRIPTION} placeholder.
```

## Sync to Windsurf

This command is mirrored at `.windsurf/workflows/new-agent.md`. When updating either version, update the other to stay in sync.

## Battle-tested in

(not yet battle-tested)

---

References:
- The Agentic Repos framework: https://github.com/ranyelhousieny/Agentic-Repo
- Templates directory in this repo: [templates/](../../templates/)
