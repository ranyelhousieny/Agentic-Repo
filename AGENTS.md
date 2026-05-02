# Agentic-Repos Framework - Claude Code Workspace Instructions

## REQUIRED: Read START_HERE.md First

Before doing ANY work in this workspace, you MUST read:

`START_HERE.md`

This file contains:
- Framework overview and mission
- How to convert repos to agentic repos
- Available agents and commands
- Knowledge base navigation

Do NOT proceed with any task until you have read START_HERE.md.

## Agent Architecture

All AI agent prompts follow a single source of truth architecture:
- **Source prompts:** `prompts/templates/AI Agents/` (full agent definitions)
- **Native Claude agents:** `.claude/agents/*.md` (auto-loaded by Claude Code)
- **Claude commands:** `.claude/commands/*.md` (invoke via `/project:command-name`)
- **Windsurf workflows:** `.windsurf/workflows/*.md` (invoke via `/workflow-name`)

When updating agents, ONLY edit source prompts. Wrappers are thin pointers.

## Available Skills

| Skill | Purpose |
|-------|---------|
| `agentic-repos-agent` | **START HERE** - Domain AI Agent. Primary session entry point, loads all knowledge, checks repo health, routes to specialists |

## Available Agents

| Agent | Color | Purpose |
|-------|-------|---------|
| `repo-analyzer` | - | Deep repo analysis: tech stack, endpoints, auth patterns |
| `knowledge-builder` | - | Build Knowledge Graph, Document Index, Source of Truth |
| `developer` | blue | Framework development: agents, commands, knowledge artifacts |
| `researcher` | teal | Evidence-based research with citations |
| `code-reviewer` | purple | Review changes for correctness and standards compliance |

## Available Commands

| Command | Description |
|---------|-------------|
| `/project:agentic-repos-ai` | **START HERE** - Activate domain agent for every session |
| `/project:convert-repo-to-agentic` | Transform any repo into agentic environment |
| `/project:analyze-repo` | Deep analysis of a repository |
| `/project:code-review` | Code review on current branch |
| `/project:generate-session-context` | Session continuity log |

## Knowledge Navigation

Use the Knowledge Graph for finding information:
`Knowledge/KNOWLEDGE_GRAPH.md`

## Zero Hallucination Policy

This workspace enforces evidence-based responses only.
Every claim must cite a source. Uncertainty must be explicit.
See `CLAUDE.md` for full rules.
