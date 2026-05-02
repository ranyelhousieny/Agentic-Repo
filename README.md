# Agentic-Repos

A framework for transforming any repository into an AI-powered agentic development environment -- battle-tested on a large-scale production API platform.

## What This Does

Takes any codebase and adds a complete agentic AI layer:
- Evidence-based Knowledge Management
- AI Agents specialized for the repo's domain
- Claude Code commands and Windsurf workflows
- Knowledge Graph for navigation
- Session continuity across AI conversations

## Quick Start: Convert Any Repo

### Via Claude Code (recommended)
```
/project:convert-repo-to-agentic <repo-path-or-url>
```

### Via Windsurf
```
/convert-repo-to-agentic
```

Then provide the repo path or GitHub/GitLab URL when prompted.

## What Gets Created

Inside the target repo:
```
{repo}/
├── CLAUDE.md                    # AI rules tailored to the tech stack
├── AGENTS.md                    # Claude Code workspace instructions
├── START_HERE.md                # Project entry point for AI sessions
├── Knowledge/
│   ├── KNOWLEDGE_GRAPH.md       # Navigation map for all knowledge
│   ├── Source of Truth/         # Authoritative project references
│   └── DOCUMENT_INDEX.md        # Topic-based quick lookup
├── Generated/                   # AI-generated artifacts land here
├── prompts/templates/AI Agents/ # Full agent definitions
└── .claude/
    ├── agents/                  # Role-specific Claude agents
    └── commands/                # Slash commands for common workflows
```

## How It Was Built

This framework was extracted from a production setup -- a large-scale API gateway project. Every pattern here was battle-tested across 86+ workflows, 40+ agents, and 12+ months of daily AI-assisted development.

## Core Principles

1. **Evidence-Based Only** - Every AI claim must cite a source
2. **Zero Hallucination** - Uncertainty is always stated explicitly
3. **Single Source of Truth** - Agents point to one authoritative prompt
4. **Session Continuity** - AI picks up where it left off, every time
5. **Knowledge Graph Navigation** - Structured navigation, no grepping blindly
6. **Generated Artifacts** - All AI output goes to `Generated/`

## Author

Rany Elhousieny - [GitHub](https://github.com/rany-ai)
