# AI Agent Prompts - Agentic-Repos Framework

This directory contains specialized AI agent prompts. These are the **source of truth** for all agents -- Claude commands and Windsurf workflows are thin wrappers that point here.

## Architecture

```
Source (here)                        Wrappers (thin pointers)
prompts/templates/AI Agents/  -->  .claude/agents/*.md
                               -->  .claude/commands/*.md
                               -->  .windsurf/workflows/*.md
```

When updating an agent, edit ONLY the source prompt. Never duplicate content into wrappers.

## Available Agents

| Agent | File | Use When |
|-------|------|----------|
| **Agentic-Repos AI** | `AGENTIC_REPOS_AI_AGENT.md` | **Start every session here** — domain expert, progress tracking |
| **Repo Onboarding** | `REPO_ONBOARDING_AGENT.md` | Converting any repo to agentic format |

## Key Features of All Agents

- **Zero Hallucination Policy** - Evidence-based only, always cite sources
- **Session Initialization** - Reads START_HERE.md + Knowledge Graph first
- **Session Continuity** - Never starts from scratch, reads progress tracker
- **Role Specialization** - Tailored context for each role
- **Date Awareness** - Runs `date` as Step 0 (AI cannot reliably calculate days of the week)

## How to Use

1. Open Claude Code or Windsurf in the target repo
2. Use a slash command: `/project:convert-repo-to-agentic`
3. Or invoke the agent directly: paste the agent prompt into a new session

## Session Continuity (CRITICAL)

Every agent must include this at the start:

```markdown
## FIRST: Session Initialization (REQUIRED)

0. Run: `date '+%A, %B %d, %Y %H:%M %Z'`
1. Read START_HERE.md
2. Read Knowledge/KNOWLEDGE_GRAPH.md
3. Read Generated/PROGRESS_TRACKER.md (if exists)
4. Summarize current state, then ask how to help.

NEVER say "Let's start by understanding the project..."
ALWAYS pick up where we left off.
```

## Creating a New Agent

1. Copy `REPO_ONBOARDING_AGENT.md` as a template
2. Replace the domain-specific sections
3. Create a thin wrapper in `.claude/commands/name.md`
4. Optionally create a native Claude agent in `.claude/agents/name.md`
5. Update this README table
