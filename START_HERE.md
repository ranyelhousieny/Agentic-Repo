# Agentic-Repos Framework - START HERE

**Read this first. Every AI session starts here.**

---

## What This Is

The Agentic-Repos framework transforms any repository into an AI-powered agentic development environment. It is directly extracted from the production architecture of a large-scale API platform built with 86+ workflows, 40+ specialized agents, and 12+ months of daily AI-assisted development.

**One command converts any repo:**

```
/project:convert-repo-to-agentic <repo-path-or-url>
```

---

## Core Mission

Give every developer, on any tech stack, the same AI-powered development environment that made the originating team 3x more productive:

- AI agents that know your codebase
- Evidence-based knowledge management
- Session continuity across conversations
- Structured navigation via Knowledge Graphs

---

## Framework Principles

| Principle                        | What It Means                                                   |
| -------------------------------- | --------------------------------------------------------------- |
| **Evidence-Based Only**          | Every AI claim cites a source: file:line or URL                 |
| **Zero Hallucination**           | Uncertainty is always stated explicitly                         |
| **Single Source of Truth**       | Agents point to one authoritative prompt, never duplicated      |
| **Session Continuity**           | AI reads progress tracker at start -- never starts from scratch |
| **Knowledge Graph Navigation**   | Structured navigation map, not blind searching                  |
| **Generated Artifacts Standard** | All AI output goes to `Generated/` directory                    |

---

## What Gets Created When You Convert a Repo

Running `/project:convert-repo-to-agentic` on any repo creates:

### Inside the Target Repo

```
{repo}/
├── CLAUDE.md                    # AI rules tailored to the tech stack
├── AGENTS.md                    # Claude Code workspace instructions
├── START_HERE.md                # Project entry point for all AI sessions
├── Knowledge/
│   ├── KNOWLEDGE_GRAPH.md       # Navigation map linking all knowledge
│   ├── Source of Truth/         # Authoritative project references (READ ONLY)
│   └── DOCUMENT_INDEX.md        # Topic-based quick lookup
├── Generated/                   # All AI-generated artifacts land here
├── prompts/templates/AI Agents/ # Full agent definitions (source of truth)
└── .claude/
    ├── agents/                  # Role-specific Claude Code agents
    │   ├── developer.md         # Tech-stack-specific developer agent
    │   ├── researcher.md        # Evidence-based research agent
    │   └── code-reviewer.md     # Code review agent
    └── commands/                # Slash commands for common workflows
        ├── code-review.md
        ├── generate-session-context.md
        └── analyze-repo.md
```

### Optional: Windsurf Integration

```
{repo}/.windsurf/
├── rules.md                     # Same rules as CLAUDE.md (Windsurf format)
└── workflows/                   # Windsurf workflow equivalents
```

---

## Start Every Session Here

```
/project:agentic-repos-ai
```

This activates the **domain agent** — the primary AI that understands the entire framework, tracks progress, and routes to specialists.

---

## Available Commands in This Workspace

| Command                             | Description                                                    |
| ----------------------------------- | -------------------------------------------------------------- |
| `/project:agentic-repos-ai`         | **START HERE** - Domain agent, progress tracking, full context |
| `/project:convert-repo-to-agentic`  | Transform any repo into a full agentic environment             |
| `/project:analyze-repo`             | Deep analysis: tech stack, endpoints, auth patterns            |
| `/project:code-review`              | Code review on current branch                                  |
| `/project:generate-session-context` | Generate session continuity log                                |

---

## Available Agents in This Workspace

| Agent               | Trigger                      | Purpose                                             |
| ------------------- | ---------------------------- | --------------------------------------------------- |
| `agentic-repos-ai`  | `/project:agentic-repos-ai`  | **Primary domain agent** — start every session here |
| `repo-analyzer`     | Auto-used by convert command | Analyzes repo structure and tech stack              |
| `knowledge-builder` | Auto-used by convert command | Builds Knowledge Graph artifacts                    |
| `developer`         | Delegated by domain agent    | Framework development tasks                         |
| `researcher`        | Delegated by domain agent    | Evidence-based research                             |
| `code-reviewer`     | `/project:code-review`       | Code review with checklist                          |

---

## How to Use

### Convert a New Repo

```bash
# GitHub repo
/project:convert-repo-to-agentic https://github.com/owner/repo.git

# GitLab repo
/project:convert-repo-to-agentic git@gitlab.com:group/repo.git

# Already-cloned repo
/project:convert-repo-to-agentic /path/to/local/repo
```

### Work With an Already-Converted Repo

Open the repo folder in Claude Code or Windsurf. The `CLAUDE.md` and `AGENTS.md` files are auto-loaded, providing full project context.

---

## Knowledge Navigation

This workspace uses the same Knowledge Graph approach as the originating production workspace.

Search in this order:

1. `Knowledge/KNOWLEDGE_GRAPH.md` - Concept relationships and navigation map
2. `Knowledge/DOCUMENT_INDEX.md` - Topic-based quick lookup
3. Full-text grep - Last resort

---

## Framework Architecture

```
Agentic-Repos (this workspace)
        |
        | uses /project:convert-repo-to-agentic
        |
        v
Any Target Repo ──> Full Agentic Stack:
                     - CLAUDE.md (project rules)
                     - AGENTS.md (workspace instructions)
                     - START_HERE.md (entry point)
                     - Knowledge/ (knowledge base)
                     - Generated/ (AI artifacts)
                     - .claude/agents/ (specialized agents)
                     - .claude/commands/ (workflows)
```

---

## Provenance

This framework is a generalized extraction of:

- A production AI workspace
- 86+ Windsurf workflows, 40+ Claude agents, 38 Claude commands
- Production-validated across multiple engineering teams
- Author: Rany Elhousieny

---

**Every AI session starts by reading this file.**
**Every claim must cite a source.**
**When in doubt -- verify, don't guess.**
