---
description: Transform any repository into a full agentic development environment with Knowledge Graph, AI agents, and Claude Code commands. Supports GitLab URLs and local paths.
---

# Convert Repo to Agentic

**Primary command for the Agentic-Repos framework.**

Transforms any repository into an AI-powered development environment with battle-tested architecture for evidence-based knowledge management -- evidence-based knowledge management, specialized AI agents, and session continuity.

**♻️ Idempotent / re-runnable.** If the target repo already has agentic content (`CLAUDE.md`, `Knowledge/`, `START_HERE.md`, `.claude/skills/<repo>-agent/`, or a domain agent), this command runs in **UPDATE mode** — it **merges/refreshes** in place (additively) rather than overwriting or duplicating: an existing `CLAUDE.md` gets the Session-Init pointer injected (never clobbered), Source of Truth is preserved, and only missing artifacts are added. Safe to run repeatedly. Details: `prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md` → Phase 2 "UPDATE MODE".

## Usage

```
/project:convert-repo-to-agentic <repo-path-or-url>
```

Examples:
```
/project:convert-repo-to-agentic git@gitlab.com:your-org/GROUP/my-service.git
/project:convert-repo-to-agentic /Users/me/code/my-service
```

## What This Command Does

Reads the full agent definition and executes it:
`prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md`

## Activation Steps

> **Framework home (works from ANY directory — required for the global symlink).**
> The framework files below (`START_HERE.md`, `Knowledge/KNOWLEDGE_GRAPH.md`,
> `prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md`) live in the **agentic-repo
> checkout**, NOT in the target repo you are converting. Resolve the framework home as:
> - If the current directory IS the agentic-repo, use `.`
> - Otherwise use your local agentic-repo checkout — default: your framework checkout
>   (clone `https://github.com/ranyelhousieny/Agentic-Repo.git` there if missing; adjust if you cloned elsewhere).
>
> All framework paths below are relative to that framework home. The **target repo** to
> convert is the path/URL passed as the command argument.

0. **Get today's date** (ALWAYS FIRST):
   Run: `date '+%A, %B %d, %Y %H:%M %Z'`

1. **Read the framework entry point:**
   `START_HERE.md`

2. **Read the Knowledge Graph:**
   `Knowledge/KNOWLEDGE_GRAPH.md`

3. **Read the full agent prompt** (source of truth for this command):
   `prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md`

4. **Adopt the role and follow all phases** defined in that file.

5. **Execute all phases:**
   - Phase 1: Discovery (detect stack, analyze structure)
   - Phase 1.5: Code Index + Dependency Graph (Graphify engine — AUTO-INSTALLS via
     `scripts/onboarding/ensure_graphify.sh`; do NOT skip. Only a proven-impossible
     install (rc 3) may skip, and it is loud: log + console + report carry the reason)
   - Phase 2: Generate all artifacts (CLAUDE.md, AGENTS.md, START_HERE.md, Knowledge/, .claude/)
   - Phase 3: Create Progress Tracker
   - Phase 4: Register in Agentic-Repos workspace
   - Phase 5: Verify and report

6. **Present completion summary** with all files created and next steps.

## What Gets Created

Inside the target repo:
- `CLAUDE.md` - AI rules tailored to the detected tech stack. If a `CLAUDE.md` already exists, it is **not overwritten** — a **Session-Init pointer block** (routing to START_HERE → Knowledge Graph → Source of Truth → domain-agent skill → Progress Tracker) is injected additively at the top so the Agentic SDLC / the pipeline honors the knowledge layer.
- `AGENTS.md` - Claude Code workspace instructions
- `START_HERE.md` - Project entry point with repo-specific content
- `BINDING.yml` - Project tracker binding (jira project, epic, board) read by ticket-creating skills. Values are derived from evidence where possible and left as `TODO:` placeholders otherwise — never guessed.
- `Knowledge/KNOWLEDGE_GRAPH.md` - Navigation map
- `Knowledge/DOCUMENT_INDEX.md` - Topic-based lookup
- `Knowledge/Source of Truth/PROJECT_VISION.md` - Template for team
- `Knowledge/SME_CONTACTS.md` - Team ownership and escalation contacts
- `Generated/PROGRESS_TRACKER.md` - Session continuity
- `prompts/templates/AI Agents/{REPO}_AI_AGENT.md` - **Domain agent (source of truth)**
- `.claude/skills/{repo}-agent/SKILL.md` - **Domain agent skill (auto-loading `@{repo}-agent`, item 4 of the injected Session-Init block)**
- `.claude/agents/developer.md` - Tech-stack-specific developer agent
- `.claude/agents/researcher.md` - Evidence-based research agent
- `.claude/agents/code-reviewer.md` - Code review agent
- `.claude/commands/{repo}-ai.md` - **Domain agent activation (START HERE)**
- `.claude/commands/code-review.md`
- `.claude/commands/generate-session-context.md`
- `.claude/commands/analyze-repo.md`

In this Agentic-Repos workspace:
- `Generated/Repos/{repo-name}_PROFILE.md` - Repo registry entry

**After conversion, start every session with:** `/project:{repo}-ai`

## Zero Hallucination Policy

All claims about the target repo must be verified from actual file contents.
Never assume tech stack, endpoints, or structure without running detection commands.
