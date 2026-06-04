---
description: "Template for a new slash command. Markdown file with frontmatter + modes + rules. Read by the AI as a prompt when the user types /your-command."
template_version: 0
status: pre-battle-tested
---

# {COMMAND_NAME} — {ONE_LINE_PURPOSE}

> **This is a template.** Replace `{COMMAND_NAME}`, `{ONE_LINE_PURPOSE}`, the modes, and rules. Strip inline `<!-- WHY -->` annotations before publishing.

{ONE_PARAGRAPH_DESCRIPTION — what this command does and when to use it}

## When the user runs `/{COMMAND_NAME}`

Parse `$ARGUMENTS` to determine which mode applies. Modes are mutually exclusive — match the FIRST keyword.

### Mode: bare `/{COMMAND_NAME}` (no arguments)

{What happens with no args. Common patterns: print current state, prompt for first arg, or run a default action.}

### Mode: `/{COMMAND_NAME} <arg-pattern-1>`

{Describe the action. Confirm in ONE line after any modification.}

### Mode: `/{COMMAND_NAME} <arg-pattern-2>`

{Add as many modes as needed. Single-purpose discipline: if you have more than ~6 modes, consider splitting into separate commands.}

## Critical rules

<!-- WHY: These rules apply to ALL commands. Bake them into every command file
     so the AI executes consistently. -->

1. **Confirm in ONE line after any modification.** Do not re-print the entire output unless the user explicitly asked for state.
2. **Idempotent.** Running the same command twice should not duplicate state.
3. **Never block on user input.** If a mode would require input, accept empty and continue. The user can fill in later.
4. **Sub-100ms target for read modes.** Commands that just display state should feel instant. Slow commands should announce expected duration.
5. **Failsafe-silent on errors.** If something goes wrong, return a single helpful line ("(registry malformed; clear with: rm ~/.claude/SESSIONS_REGISTRY.json)") and exit. Don't break the user's prompt flow.

## Sync to Windsurf

If this command should also work in Windsurf, mirror it at `.windsurf/workflows/{COMMAND_NAME}.md`. When updating either version, update the other to stay in sync.

## Battle-tested in

<!-- TODO when instantiating: replace with 1-3 real projects where this command has been used. Use generic descriptors only — no employer or client identifiers. Until first use, leave as `(not yet battle-tested)`. -->

(not yet battle-tested)

---

## Why this template exists (delete from your published command file)

Slash commands in Claude Code (and Windsurf) are markdown files the AI reads as a prompt. There's no executable code; the AI interprets the instructions and executes them. This template encodes the conventions that emerged from running 30+ commands:

1. **Frontmatter description** is what surfaces in the skill/command list. Keep it under 80 chars and lead with the action.
2. **Mode-based dispatch** keeps a single command focused while allowing variants. The "match FIRST keyword" rule prevents ambiguity.
3. **One-line confirmations** prevent commands from filling the chat with noise during routine use.
4. **Idempotency** is critical because commands often get re-run (intentionally or by mistake).

References:

**Original work this template draws from (Rany ElHousieny):**
- The Agentic Repos framework (open source): https://github.com/ranyelhousieny/Agentic-Repo
- Building an AI-Powered Markdown Knowledge Base — Medium, Apr 2026: https://medium.com/cwan-engineering/building-an-ai-powered-markdown-knowledge-base-system-for-your-engineering-team-4bccea3cdbfe
- LinkedIn: https://linkedin.com/in/rany-ai/
