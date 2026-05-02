# Agentic Framework - Source of Truth

**Status:** READ ONLY - Authoritative Design Principles
**Authority:** Framework Author (Rany Elhousieny)
**Derived From:** A production API platform workspace (2025-2026)

---

## What is an Agentic Repository?

A standard repository contains code. An agentic repository contains code PLUS a complete AI knowledge layer that enables AI agents to:

1. **Understand** the codebase without manual explanation
2. **Navigate** knowledge without blind searching
3. **Maintain continuity** across sessions (picks up where it left off)
4. **Generate evidence-based** responses, never hallucinating
5. **Specialize** by role (developer, reviewer, architect, etc.)

---

## Core Design Principles

### Principle 1: Evidence-Based Only

Every AI claim must cite a verifiable source. This is non-negotiable.

**Why:** Financial systems, production code, and mission-critical infrastructure require traceable decisions. "I think" and "probably" have no place in engineering decisions.

**Format:**
```
CLAIM: [Statement]
SOURCE: [file:line or URL]
CONFIDENCE: HIGH | MEDIUM | LOW
VERIFIED: [date or "Not yet verified"]
```

### Principle 2: Single Source of Truth

Agent prompts live in ONE location (`prompts/templates/AI Agents/`). Wrappers (commands, workflows, skills) are thin pointers. Never duplicate content.

**Why:** Duplication leads to drift. When one copy is updated, the other becomes stale. In a system with 40+ agents, this creates chaos.

**Pattern:**
```
Source:  prompts/templates/AI Agents/AGENT_NAME.md  (full definition)
Claude:  .claude/agents/name.md                      (thin wrapper)
Command: .claude/commands/name.md                    (slash command)
Windsurf:.windsurf/workflows/name.md                 (workflow wrapper)
```

### Principle 3: Session Continuity

Every AI session begins by reading:
1. `START_HERE.md` - Current context
2. `Knowledge/KNOWLEDGE_GRAPH.md` - Navigation map
3. `Generated/PROGRESS_TRACKER.md` - Where we left off

**Why:** Without this, every conversation starts from scratch. Users waste time re-explaining context. With this, AI picks up exactly where it left off.

**Anti-patterns to avoid:**
- "Let's start by understanding the project..."
- "What are your goals?"
- "Tell me about your codebase..."

### Principle 4: Knowledge Graph Navigation

Knowledge is organized in a graph structure with:
- **Authority tiers** (Source of Truth > Knowledge > Generated)
- **Concept clusters** (grouped by topic)
- **Search index** (keyword → document mapping)

**Why:** `grep -r "keyword" .` is not knowledge management. A structured graph enables AI agents to find information in O(1) lookups instead of O(n) searches.

### Principle 5: Generated Artifacts Standard

All AI-generated content goes to `Generated/`. Knowledge is read-only. Source of Truth is immutable.

**Why:** Mixing AI output with authoritative knowledge corrupts the knowledge base. Clear separation enables trust: if it's in `Knowledge/Source of Truth/`, it's been verified by a human authority.

### Principle 6: Role Specialization

Different roles need different context. A developer agent needs different instructions than an architect agent or a scrum master agent.

**Why:** Generic agents produce generic output. Specialized agents with domain context produce expert-level output.

---

## What Gets Created When Converting a Repo

The convert command creates a complete agentic stack:

### Knowledge Layer
| File | Purpose |
|------|---------|
| `START_HERE.md` | Entry point for every AI session |
| `CLAUDE.md` | Rules tailored to the repo's tech stack |
| `AGENTS.md` | Claude Code workspace instructions |
| `Knowledge/KNOWLEDGE_GRAPH.md` | Navigation map |
| `Knowledge/Source of Truth/PROJECT_VISION.md` | Template for team to fill |
| `Knowledge/DOCUMENT_INDEX.md` | Topic-based lookup |
| `Generated/PROGRESS_TRACKER.md` | Session continuity tracker |

### Agent Layer
| File | Purpose |
|------|---------|
| `prompts/templates/AI Agents/{NAME}_AI_AGENT.md` | **Domain agent** — primary session entry point |
| `.claude/agents/developer.md` | Tech-stack-specific developer agent |
| `.claude/agents/researcher.md` | Evidence-based research agent |
| `.claude/agents/code-reviewer.md` | Code review agent |

### Command Layer
| File | Purpose |
|------|---------|
| `.claude/commands/{name}-ai.md` | `/project:{name}-ai` — **activate domain agent** |
| `.claude/commands/code-review.md` | `/project:code-review` |
| `.claude/commands/generate-session-context.md` | `/project:generate-session-context` |
| `.claude/commands/analyze-repo.md` | `/project:analyze-repo` |

### Optional: Windsurf Layer
| File | Purpose |
|------|---------|
| `.windsurf/rules.md` | Same rules as CLAUDE.md (Windsurf format) |
| `.windsurf/workflows/*.md` | Workflow equivalents of commands |

---

## Tech Stack Detection Rules

When analyzing a repo, detect the following and adapt the generated agents accordingly:

| Stack | Detection | Agent Adaptation |
|-------|-----------|-----------------|
| Java/Spring Boot | `pom.xml` + `@SpringBootApplication` | Spring patterns, Maven commands |
| Java/JAX-RS | `pom.xml` + `@Path` annotations | JAX-RS routing, REST patterns |
| Kotlin/Spring | `build.gradle.kts` + Kotlin sources | Kotlin idioms, Gradle |
| Python/FastAPI | `requirements.txt` + `@app.get` | FastAPI routing, async patterns |
| Python/Django | `manage.py` + `urlpatterns` | Django ORM, URL patterns |
| Node/Express | `package.json` + `app.use\|router` | Express middleware, npm |
| Node/NestJS | `package.json` + `@Controller` | NestJS decorators, TypeScript |
| Terraform | `*.tf` files | HCL syntax, resource patterns |
| Mixed | Multiple detected | Polyglot agent with all patterns |

---

## Authority Hierarchy for Conflicts

When two documents conflict:
1. `Knowledge/Source of Truth/` wins (always)
2. `Knowledge/*.md` (non-generated)
3. `Generated/*.md`
4. Conversation context

---

## Evolution of This Framework

This framework evolved from a production API platform workspace (2025-2026):

| Milestone | What Was Added |
|-----------|----------------|
| Q4 2025 | Basic agent prompts, Windsurf workflows |
| Q1 2026 | Knowledge Graph, Source of Truth tier, session continuity |
| Feb 2026 | Claude Code native agents, `.claude/agents/` pattern |
| Mar 2026 | `repo-to-knowledge-graph` workflow, in-repo artifacts |
| Apr 2026 | Generalized as Agentic-Repos framework |

---

**This document is READ ONLY. To propose changes, open a GitHub issue or PR.**
