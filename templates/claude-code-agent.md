---
description: "Template for a new Claude Code agent. Encodes the conventions that emerged from running 10+ parallel agentic sessions: intent-on-activation, hook-aware surfacing, fast-mode for quick questions, START_HERE/KG reads, sub-100ms init."
template_version: 0
status: pre-battle-tested
---

# {AGENT_NAME} Agent

> **This is a template.** Replace `{AGENT_NAME}`, `{ROLE_DESCRIPTION}`, the example greetings, and the "Battle-tested in" section with your specifics. Strip the inline `<!-- WHY -->` annotations before publishing your final agent file.

## Role

{ROLE_DESCRIPTION}

## Session Steps (REQUIRED at activation)

<!-- WHY: Step 0 must run BEFORE any slow read/sync. The user often types
     `/your-agent <intent>` and immediately tab-switches while initialization
     happens in the background. If Step 0 is later in the order, the user
     comes back to a tab where they've forgotten the intent. -->

0. **Capture intent FIRST (must complete in <100ms before any slow operation):**
   - If `$ARGUMENTS` is provided: write `**Goal:** $ARGUMENTS` and current timestamp to `.claude/CONTEXT.md` using `/track <goal>` semantics. Preserve existing Pivots; reset Done/Stuck-on/Remaining only if Goal differs.
   - If `$ARGUMENTS` is empty AND `.claude/CONTEXT.md` exists with timestamp <2 hours old: silently reuse the existing Goal.
   - If `$ARGUMENTS` is empty AND no recent CONTEXT.md: emit one line `(Goal not set — use /track <goal> anytime)` and continue. Do NOT block initialization on user input.

0.5. **Fast-mode detection (skip slow init for quick questions):**
   - If `$ARGUMENTS` starts with `quick:`, `fast:`, `q:`, or contains `--fast` / `?fast`, treat as a quick-question mode:
     - Strip the magic prefix/flag from the goal text before writing CONTEXT.md
     - SKIP steps 1, 2, 3 (no START_HERE, no KG, no task-specific reads)
     - Go directly to step 4 (greeting) and answer the question using whatever is already in CONTEXT.md plus your domain knowledge
     - Mark fast mode explicitly in your greeting: "(fast mode — skipped project-context reads)"
   - Otherwise, proceed normally.
   - **Why:** sometimes you just need a one-off answer without 30 seconds of file reads. Fast mode trades context-completeness for speed.

<!-- WHY: START_HERE.md is the agent's first read because it carries
     project-level context that doesn't change session to session.
     KNOWLEDGE_GRAPH.md is the navigation map for everything else. -->

1. Read `START_HERE.md` for current project context.

2. Read `Knowledge/KNOWLEDGE_GRAPH.md` (or your project's KG file) for navigation.

3. Read any task-specific knowledge files relevant to `$ARGUMENTS` (skip if not applicable).

4. **Greet the user** with one sentence summarizing their goal, plus the top-3 most relevant remaining items from CONTEXT.md if any. Then ask what specific task to start with.

## Core Responsibilities

{Define 3-5 core responsibilities for this agent.}

## Communication Style

{Optional. Default: terse, evidence-led. Override for specific tones (warmer for coaching agents, more cautious for security agents).}

## Sync to Windsurf

This agent is mirrored in Windsurf at `.windsurf/workflows/{AGENT_NAME}.md`. When updating either version, update the other to stay in sync. See [windsurf-workflow.md template](./windsurf-workflow.md).

## Battle-tested in

<!-- TODO when instantiating: replace this section with 1-3 real projects where this agent has been applied. Use generic descriptors only ("an enterprise data platform," "a personal career repo") — no employer or client identifiers. Until you've used this agent on a real project, leave this section as just `(not yet battle-tested)`. -->

(not yet battle-tested)

---

## Why this template exists (delete from your published agent file)

The conventions encoded here came from running 10+ parallel Claude Code sessions and discovering:

1. **Hook injection beats agent-file instructions.** Lines like "read CONTEXT.md on activation" in agent files are advisory and routinely skipped under cognitive load. The UserPromptSubmit hook injects deterministically. Step 0 only ensures the file *exists*; the hook handles surfacing.

2. **Intent must be captured BEFORE slow init.** Agents that do JIRA syncs, KG reads, or file walks take 5-30 seconds. Users tab-switch during this time and forget why they opened the tab. Step 0 closes that gap with a sub-100ms write.

3. **Fast mode is non-optional for daily use.** Without an opt-out, agents become too heavy for quick questions and users stop activating them.

4. **Per-project CONTEXT.md is per-tab state.** A global registry (`~/.claude/SESSIONS_REGISTRY.json`) provides cross-tab awareness. New agents inherit both layers automatically by following Step 0.

References:

**Original work this template draws from (Rany ElHousieny):**
- The Agentic Repos framework (open source): https://github.com/ranyelhousieny/Agentic-Repo
- Building an AI-Powered Markdown Knowledge Base — Medium, Apr 2026: https://medium.com/cwan-engineering/building-an-ai-powered-markdown-knowledge-base-system-for-your-engineering-team-4bccea3cdbfe
- LinkedIn: https://linkedin.com/in/rany-ai/

**Industry prior art that converged on similar patterns:**
- HumanLayer's progress.md: https://github.com/humanlayer/advanced-context-engineering-for-coding-agents
- Addy Osmani's long-running agents: https://addyo.substack.com/p/long-running-agents
- Augment Code's AGENTS.md spec: https://www.augmentcode.com/guides/context-engineering-enhancing-agentic-swarm-coding-through-intent-environment-and-system-memory
