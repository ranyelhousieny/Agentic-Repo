# Agentic-Repos Framework - Rules for Claude Code

**CRITICAL: These rules apply to ALL AI interactions in this workspace.**

**Purpose:** Transform any repository into an AI-powered agentic development environment.
**Status:** MANDATORY - Enforced for every prompt and response
**Last Updated:** April 7, 2026

---

## ZERO HALLUCINATION POLICY

Every claim must be verifiable. Every uncertainty must be explicit. Every output must be traceable to authoritative sources.

This applies to ALL repos analyzed or converted by this framework.

---

## Rule 0: Session Initialization (ALWAYS FIRST)

Before doing ANY work in a session:
1. Read `START_HERE.md` - Framework overview and current context
2. Read `Knowledge/KNOWLEDGE_GRAPH.md` - Navigation map
3. Read `Generated/PROGRESS_TRACKER.md` if it exists

---

## Rule 1: Evidence-Based Responses Only

Every factual claim must cite a specific source:
- Verified code: file path and line numbers
- Official documentation: URL and access date
- Command output: exact terminal results
- Internal documents: file path

**If you cannot cite a source:**
- Say "I don't have evidence for this"
- Say "This requires verification from [source type]"
- Say "This is my understanding but needs confirmation from [source]"

**Never:**
- State opinions as facts
- Rely on "common knowledge" without citation
- Assume without verification

---

## Rule 2: Explicit Uncertainty

When uncertain, use EXACTLY these phrases:
- "I am not certain about this - please verify"
- "This is my understanding, but it needs confirmation from [source]"
- "I cannot find authoritative evidence for this claim"

**Mark confidence levels on all technical claims:**
- **HIGH:** Official docs, verified code, confirmed by authoritative source
- **MEDIUM:** General knowledge, needs current verification
- **LOW:** Inference, assumption, or speculation - requires validation

---

## Rule 3: No Speculation

Absolutely forbidden:
- Guessing API endpoints, URLs, or configuration values
- Assuming how internal systems work without evidence
- Filling gaps with plausible-sounding information
- Inventing versions, specifications, or timelines

---

## Rule 4: Source of Truth

`Knowledge/Source of Truth/` is THE authoritative, read-only reference.

Rules:
1. NEVER modify Source of Truth files
2. All derivative files MUST align with Source of Truth
3. When conflicts exist - Source of Truth wins

---

## Rule 5: Technical Claims Format

For any technical claim, use this format:

```
CLAIM: [Your statement]
SOURCE: [Exact source - URL, file path, or documentation name with line number]
CONFIDENCE: [HIGH | MEDIUM | LOW]
VERIFIED: [Date or "Not yet verified"]
```

---

## Rule 6: Forbidden Actions

You are PROHIBITED from:

1. Making up file paths, endpoints, or identifiers not verified from sources
2. Inventing configuration values or parameters
3. Claiming knowledge beyond what is documented
4. Providing code that cannot be verified to work
5. Modifying Source of Truth files
6. Contradicting Source of Truth documents
7. Outputting lengthy analysis to chat instead of markdown files
8. Skipping systematic discovery when analyzing repositories

---

## Rule 7: Agent Architecture (Single Source of Truth)

All AI agent prompts follow this architecture:
- **Source prompts:** `prompts/templates/AI Agents/` (full definitions)
- **Claude Code agents:** `.claude/agents/*.md` (native Claude agents with YAML frontmatter)
- **Claude Code commands:** `.claude/commands/*.md` (slash command wrappers)
- **Windsurf workflows:** `.windsurf/workflows/*.md` (thin wrappers pointing to source)

When updating agents, ONLY edit source prompts. Never duplicate content into wrappers.

---

## Rule 8: Knowledge Graph Navigation

Always search in this order:
1. `Knowledge/KNOWLEDGE_GRAPH.md` - Concept relationships
2. `Knowledge/DOCUMENT_INDEX.md` - Topic-based quick lookup
3. Full-text grep - Last resort only

When adding or modifying ANY knowledge document:
1. Update `Knowledge/KNOWLEDGE_GRAPH.md`
2. Update `Knowledge/DOCUMENT_INDEX.md`
3. Update timestamps in both files

---

## Rule 9: Generated Artifacts Standard

ALL AI-generated content MUST be saved to the `Generated/` directory.

Naming convention:
- Analysis: `Generated/Analysis/YYYY-MM-DD_[description].md`
- Reports: `Generated/Reports/YYYY-MM-DD_[topic].md`
- Session logs: `Generated/session_logs/YYYY-MM-DD_[topic]_session.md`
- Repo profiles: `Generated/Repos/[repo-name]_PROFILE.md`

Do NOT save to: root directory, `Knowledge/` (read-only), `prompts/` (templates only)

---

## Rule 10: Diagram Documentation Standard

Every diagram MUST include all three formats:
1. **Mermaid code** - Source in fenced code block
2. **Text/ASCII diagram** - For accessibility and plain-text environments
3. **PNG link** - Via mermaid.ink for rendered version

---

## Rule 11: .env File Parsing (CRITICAL - TOKEN TRUNCATION BUG)

NEVER use `cut -d'=' -f2` to parse .env values. Tokens contain `=` characters that get silently truncated.

**Correct pattern (ALWAYS use `-f2-` with trailing dash):**
```bash
export VAR=$(grep '^VAR=' .env | cut -d'=' -f2-)
```

**NEVER use:**
```bash
cut -d'=' -f2    # WRONG: Truncates value at embedded = signs
source .env       # WRONG: Fails if .env has non-shell lines
```

Each `run_command` is a NEW shell. Source `.env` in the SAME command:
```bash
/bin/zsh -c 'source .env && python3 tool.py ARGS'
```

---

## Rule 12: Git Conventions

Branch naming: `TICKET-description` or `feature/description`
Commit format: `TICKET: Description` or `feat: Description`

Before pushing:
1. `git fetch origin main`
2. `git rebase origin/main`
3. `git push origin BRANCH --force-with-lease`

---

## Rule 13: Creating Claude Code Agents

Agents are specialized AI assistants defined by markdown files.

**Locations:**
- Source prompt: `prompts/templates/AI Agents/{NAME}_AGENT.md`
- Native Claude agent: `.claude/agents/{name}.md` (with YAML frontmatter)
- Command wrapper: `.claude/commands/{name}.md`

**Required sections in every agent:**
1. Agent Identity (who it is, specializations)
2. Session Initialization (read START_HERE.md → Knowledge Graph → Progress Tracker)
3. Core Mission
4. Zero Hallucination Protocol
5. Workflow (Discovery → Analysis → Output phases)
6. Output Templates
7. Quality Checklist

**Native Claude agent frontmatter format:**
```yaml
---
name: agent-name
description: "When to use this agent. Include example triggers."
model: sonnet
color: blue
---
```

---

## Rule 14: Session Log Location

Save session logs in the folder you are actively working on:
- Repo analysis work → `Generated/Repos/[repo-name]_session.md`
- Framework work → `Generated/session_logs/YYYY-MM-DD_[topic]_session.md`

---

## Available Custom Commands

| Command | Description |
|---------|-------------|
| `/project:agentic-repos-ai` | **START HERE** - Domain agent, progress tracking, full context |
| `/project:convert-repo-to-agentic` | Transform any repo into a full agentic environment |
| `/project:analyze-repo` | Deep analysis of a repository (tech stack, endpoints, auth) |
| `/project:code-review` | Code review on current branch changes |
| `/project:generate-session-context` | Generate session context log for continuity |

---

## Directory Structure

```
Agentic-repos/
├── CLAUDE.md                      # Rules for Claude Code (this file)
├── AGENTS.md                      # Claude Code workspace instructions
├── START_HERE.md                  # Framework entry point
├── README.md                      # Public documentation
├── Knowledge/
│   ├── KNOWLEDGE_GRAPH.md         # Navigation map
│   ├── Source of Truth/           # Authoritative framework docs (READ ONLY)
│   └── DOCUMENT_INDEX.md          # Topic-based quick lookup
├── Generated/
│   ├── Repos/                     # Profiles of converted repos
│   ├── Analysis/                  # Analysis artifacts
│   ├── Reports/                   # Reports
│   └── session_logs/              # Session continuity logs
├── prompts/
│   └── templates/
│       └── AI Agents/             # Full agent definitions (source of truth)
└── .claude/
    ├── agents/                    # Native Claude Code agents
    └── commands/                  # Slash commands
```

---

## Response Checklist

Before any response, verify:
- [ ] Every factual claim has a source or is marked uncertain
- [ ] No paths, endpoints, or configurations are invented
- [ ] Uncertainty is explicitly stated with confidence level
- [ ] Source of Truth files are not modified
- [ ] All artifacts saved to Generated/ directory
- [ ] Knowledge Graph updated if new knowledge added
- [ ] Diagrams include all three formats

---

**These rules are non-negotiable. Quality over speed. Evidence over assumptions. Clarity over confidence.**
