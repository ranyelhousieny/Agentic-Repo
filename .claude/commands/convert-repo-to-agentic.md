---
description: Transform any repository into a full agentic development environment with Knowledge Graph, AI agents, and Claude Code commands. Supports GitHub URLs, GitLab URLs, and local paths.
---

# Convert Repo to Agentic

**Primary command for the Agentic-Repos framework.**

Transforms any repository into an AI-powered development environment with battle-tested architecture for evidence-based knowledge management, specialized AI agents, and session continuity.

## Usage

```
/project:convert-repo-to-agentic <repo-path-or-url>
```

Examples:

```
/project:convert-repo-to-agentic https://github.com/owner/my-service.git
/project:convert-repo-to-agentic git@gitlab.com:group/my-service.git
/project:convert-repo-to-agentic /path/to/your/repo
```

## What This Command Does

Reads the full agent definition and executes it:
`prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md`

## Activation Steps

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
   - Phase 2: Generate all artifacts (CLAUDE.md, AGENTS.md, START_HERE.md, Knowledge/, .claude/)
   - Phase 3: Create Progress Tracker
   - Phase 4: Register in Agentic-Repos workspace
   - Phase 5: Verify and report

6. **Present completion summary** with all files created and next steps.

## What Gets Created

Inside the target repo:

- `CLAUDE.md` - AI rules tailored to the detected tech stack
- `AGENTS.md` - Claude Code workspace instructions
- `START_HERE.md` - Project entry point with repo-specific content
- `Knowledge/KNOWLEDGE_GRAPH.md` - Navigation map (see Knowledge Graph Standard below)
- `Knowledge/DOCUMENT_INDEX.md` - Topic-based lookup
- `Knowledge/Source of Truth/PROJECT_VISION.md` - Template for team
- `Generated/PROGRESS_TRACKER.md` - Session continuity
- `prompts/templates/AI Agents/{REPO}_AI_AGENT.md` - **Domain agent (source of truth)**
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

## Knowledge Graph Standard (mandatory)

Every generated `Knowledge/KNOWLEDGE_GRAPH.md` must contain all of these sections, matching the reference-quality bar:

1. Document Hierarchy and Authority (Tiers 1-4, Source of Truth wins conflicts)
2. Relationship Graph (Mermaid `graph TB` of tiers and major docs)
3. Concept Clusters (file tables + Key Questions)
4. Quick Reference: Common Questions (question to document)
5. Evidence Tracing (Claim to source files)
6. Search Index (Keyword to document)

Plus a New Team Member Path and a Maintenance section (add/update/deprecate rules + Version History) so the map stays current. Canonical format: `.claude/agents/knowledge-builder.md` Step 3. A map missing the Relationship Graph, Evidence Tracing, or Maintenance is incomplete.

## Zero Hallucination Policy

All claims about the target repo must be verified from actual file contents.
Never assume tech stack, endpoints, or structure without running detection commands.
