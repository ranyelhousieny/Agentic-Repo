---
description: "Template for a new Windsurf workflow. Mirrors templates/claude-code-agent.md with Cascade-specific surfacing — there's no deterministic prompt-submit hook in Windsurf today, so .windsurfrules + Cascade Memories provide best-effort surfacing of CONTEXT.md."
template_version: 0
status: pre-battle-tested
---

# {WORKFLOW_NAME} Workflow

> **This is a template.** Replace `{WORKFLOW_NAME}`, `{ROLE_DESCRIPTION}`, the example greetings, and the "Battle-tested in" section with your specifics. Strip the inline `<!-- WHY -->` annotations before publishing your final workflow file.

## Role

{ROLE_DESCRIPTION}

## Activation Steps (REQUIRED)

<!-- WHY: Step 0 must run BEFORE any slow read/sync. The user often types
     `/your-workflow <intent>` and immediately tab-switches while initialization
     happens in the background. Without Step 0, they come back to a tab where
     they've forgotten the intent. -->

0. **Capture intent FIRST (must complete in <100ms before any slow operation):**
   - If `$ARGUMENTS` is provided: write `**Goal:** $ARGUMENTS` and current timestamp to `.claude/CONTEXT.md` using `/track <goal>` semantics. Preserve existing Pivots; reset Done/Stuck-on/Remaining only if Goal differs. Note: the file lives at `.claude/CONTEXT.md` (not `.windsurf/`) by convention so both Claude Code and Windsurf workflows share state in the same project.
   - If `$ARGUMENTS` is empty AND `.claude/CONTEXT.md` exists with timestamp <2 hours old: silently reuse the existing Goal.
   - If `$ARGUMENTS` is empty AND no recent CONTEXT.md: emit one line `(Goal not set — use /track <goal> anytime)` and continue. Do NOT block initialization on user input.

0.5. **Fast-mode detection (skip slow init for quick questions):**
   - If `$ARGUMENTS` starts with `quick:`, `fast:`, `q:`, or contains `--fast` / `?fast`, treat as a quick-question mode:
     - Strip the magic prefix/flag from the goal text before writing CONTEXT.md
     - SKIP steps 1, 2, 3 (no START_HERE, no KG, no task-specific reads)
     - Go directly to step 4 (greeting) and answer the question using whatever is already in CONTEXT.md plus your domain knowledge
     - Mark fast mode explicitly: "(fast mode — skipped project-context reads)"
   - Otherwise, proceed normally.

<!-- WHY: START_HERE.md and KNOWLEDGE_GRAPH.md are project-level context
     that doesn't change session to session. Read once, use throughout. -->

1. Read `START_HERE.md` for current project context.

2. Read `Knowledge/KNOWLEDGE_GRAPH.md` (or your project's KG file) for navigation.

3. Read any task-specific knowledge files relevant to `$ARGUMENTS` (skip if not applicable).

4. **Greet the user** with one sentence summarizing their goal, plus the top-3 most relevant remaining items from CONTEXT.md if any. Then ask what specific task to start with.

## Cascade-specific surfacing (the IDE-asymmetry note)

Claude Code has a deterministic `UserPromptSubmit` hook that injects `.claude/CONTEXT.md` content into every prompt. **Windsurf has no equivalent today.** Workarounds:

1. **`.windsurfrules` reference** (recommended). Add this line to your project's `.windsurfrules`:
   ```
   Always load @.claude/CONTEXT.md as session context if it exists. Treat its content as the user's active goal, done items, stuck-on, and remaining work for this session.
   ```
   This is **advisory** (Cascade may skip under load) but is the closest equivalent to a hook. Worth doing.

2. **Cascade Memories**. As `/track` updates run, the workflow can use Cascade's Memory feature to save the active Goal as a Memory. Memories are first-party persistent state. Trade-off: Memories are global, not per-project, so multi-project users may see Memory pollution.

3. **Honest limitation.** Cascade greetings should reference CONTEXT.md content explicitly (not assume the IDE injected it) until Windsurf ships a real prompt-submit hook.

## Core Responsibilities

{Define 3-5 core responsibilities for this workflow.}

## Communication Style

{Optional. Default: terse, evidence-led. Override for specific tones (warmer for coaching, more cautious for security).}

## Sync to Claude Code

This workflow is mirrored in Claude Code at `.claude/commands/{WORKFLOW_NAME}.md` (or `.claude/agents/{WORKFLOW_NAME}.md` if it's an agent prompt). When updating either version, update the other to stay in sync. See [claude-code-agent.md template](./claude-code-agent.md).

## Battle-tested in

<!-- TODO when instantiating: replace this section with 1-3 real projects where this workflow has been applied. Use generic descriptors only ("an enterprise data platform," "a personal career repo") — no employer or client identifiers. Until you've used this workflow on a real project, leave this section as just `(not yet battle-tested)`. -->

(not yet battle-tested)

---

## Why this template exists (delete from your published workflow file)

The conventions encoded here mirror the Claude Code agent template, with one important asymmetry:

- **Claude Code has deterministic prompt-submit hooks.** Lines like "read CONTEXT.md on activation" can fail because they're advisory, but the `UserPromptSubmit` hook injects deterministically.
- **Windsurf does not.** `.windsurfrules` is always-loaded but advisory; Cascade can ignore it under load. Cascade Memories are first-party but global.

This means **Windsurf workflows must explicitly reference CONTEXT.md content in their greeting** rather than assume the IDE injected it. That's the one behavioral difference from the Claude Code agent template. Otherwise, Step 0 inline-intent capture, fast-mode detection, START_HERE/KG reads, and the greeting format are identical — by design, so you can mirror your Claude Code agents into Windsurf with minimal divergence.

References:

**Original work this template draws from (Rany ElHousieny):**
- The Agentic Repos framework (open source): https://github.com/ranyelhousieny/Agentic-Repo
- Building an AI-Powered Markdown Knowledge Base — Medium, Apr 2026: https://medium.com/cwan-engineering/building-an-ai-powered-markdown-knowledge-base-system-for-your-engineering-team-4bccea3cdbfe
- LinkedIn: https://linkedin.com/in/rany-ai/

**Industry prior art that converged on similar patterns:**
- HumanLayer's progress.md: https://github.com/humanlayer/advanced-context-engineering-for-coding-agents
- Addy Osmani's long-running agents: https://addyo.substack.com/p/long-running-agents
- Augment Code's AGENTS.md spec: https://www.augmentcode.com/guides/context-engineering-enhancing-agentic-swarm-coding-through-intent-environment-and-system-memory
