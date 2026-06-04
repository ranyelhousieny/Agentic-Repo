---
description: "/modernize-agent <path> — diff an existing agent/workflow/command/skill/pattern against the current template. Proposes the smallest set of additions to bring it up to current conventions. User accepts/rejects per-line."
---

# /modernize-agent — Audit an existing artifact against the current template

Read an existing artifact, diff against its corresponding template in `Agentic-Repo/templates/`, and propose the minimum set of additions to bring it up to current conventions. The user reviews and accepts/rejects per-line — nothing is changed without explicit approval.

Pair with `/new-agent` (which creates a fresh artifact from the same templates).

## When the user runs `/modernize-agent <path>`

Required argument:
- `<path>` — absolute or relative path to the existing artifact (e.g., `~/.claude/commands/my-old-agent.md`).

### Step 1 — Detect the artifact type

Inspect the file path and content to determine which template applies:
- File at `~/.claude/commands/*.md` or `.claude/commands/*.md` → likely `claude-agent` or `slash-command`
  - Look at content: if it has "Session Steps" or "Activation Steps" or "Role" headings, treat as claude-agent
  - Otherwise treat as slash-command
- File at `.windsurf/workflows/*.md` → `windsurf-workflow`
- File at `~/.claude/skills/*/SKILL.md` or contains "Trigger when" / "Skip when" → `skill`
- File at `Knowledge/patterns/*.md` or contains "## TL;DR" + "## Problem" + "## Solution" → `pattern-doc`

If type cannot be detected unambiguously, ask the user: `Could not auto-detect type. Please run with explicit type: /modernize-agent <path> --type=<claude-agent|windsurf-workflow|slash-command|skill|pattern-doc>`.

### Step 2 — Load the template

Read the corresponding template from `Agentic-Repo/templates/`. Note the section headings, required placeholders, and conventions encoded.

### Step 3 — Diff

Compare the existing artifact against the template:

- **Missing sections** — sections present in the template but absent from the artifact (e.g., no "Step 0" in an agent that should have it; no "Skip when" in a skill).
- **Stale conventions** — older patterns that have been replaced (e.g., agent reads `PARKED.md` instead of `.claude/CONTEXT.md`; agent doesn't have fast-mode detection).
- **Missing references block** — template has a References section with Rany's work + industry prior art; artifact doesn't.
- **Missing Sync note** — template has a "Sync to {other-IDE}" note; artifact doesn't.
- **Missing Battle-tested-in section** — template has it; artifact doesn't.

For each gap, generate the minimum patch (insert a section, replace stale text, append references).

### Step 4 — Present the proposed changes

Print a structured diff with each proposed change as a numbered item:

```
Proposed changes for <path>:

1. ADD Step 0 (intent capture) before existing Step 1 in "Session Steps":
   <proposed text>

2. ADD fast-mode detection as Step 0.5 after Step 0:
   <proposed text>

3. REPLACE "PARKED.md" references with ".claude/CONTEXT.md" (3 occurrences in this file):
   <line-by-line diff>

4. ADD "Battle-tested in" section before final References:
   <proposed text>

5. ADD References section at end:
   <proposed text>

Reply with:
- `accept all` to apply all changes
- `accept 1,3,5` to apply only specific items
- `reject` to make no changes
- Or describe specific edits to make instead
```

### Step 5 — Apply only what the user accepted

After the user replies, apply only the accepted changes. Print one-line confirmation: `Applied <N> changes to <path>. Skipped <M>.`

### Step 6 — Suggest a follow-up

If the artifact is now up-to-date but still missing battle-tested-in evidence, remind: `Note: Battle-tested in section is empty. Fill in 1-3 real projects (anonymized) once you've used this artifact in production.`

## Critical rules

1. **Never modify without explicit user approval.** This is a propose-and-apply tool, not an auto-fix tool.
2. **Minimum patch.** Don't reformat or restructure beyond the specific gap. The artifact's existing content is the user's work — preserve it.
3. **Diff format must be readable.** If a proposed change is more than ~5 lines, summarize it ("ADD Section X with the standard template content") and let the user accept-then-review.
4. **Never delete user content.** If a section in the artifact has been customized away from the template, leave the customization. Only flag if it conflicts with a HARD invariant (e.g., the file has no Step 0 at all).

## Sync to Windsurf

This command is mirrored at `.windsurf/workflows/modernize-agent.md`. When updating either version, update the other to stay in sync.

## Battle-tested in

(not yet battle-tested)

---

References:
- The Agentic Repos framework: https://github.com/ranyelhousieny/Agentic-Repo
- Templates directory in this repo: [templates/](../../templates/)
- Pair: [/new-agent](./new-agent.md) (for fresh artifacts)
