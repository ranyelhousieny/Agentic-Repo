# Agentic-Repos Knowledge Graph

**Purpose:** Navigation map for all knowledge in this framework. AI agents use this to efficiently find information without guessing.

**Last Updated:** April 8, 2026 (v1.3 - Enhanced convert-repo-to-agentic with skill, Jira sync, SME contacts, cross-workspace)
**Maintainer:** Auto-updated by agents on significant changes

---

## How to Use This Knowledge Graph

### For AI Agents

1. **Search by concept** - Find all documents for a topic
2. **Follow authority tiers** - Higher tier = more authoritative
3. **Trace evidence** - Find source documents for specific claims
4. **Discover dependencies** - What knowledge is prerequisite to what

### For Developers

1. **Onboarding** - Follow the "New User Path" below
2. **Deep Dive** - Use concept clusters to explore specific areas
3. **Decision Making** - Reference authoritative sources

---

## Document Hierarchy and Authority

### Tier 1: Source of Truth (READ ONLY)

```
Knowledge/Source of Truth/
├── AGENTIC_FRAMEWORK.md          [Framework principles and design decisions]
├── PROJECT_VISION.md             [Project mission, goals, success criteria]
└── README.md                     [Source of Truth documentation]
```

**Rules:** Never modify. All derivatives must align. Source of Truth wins in conflicts.

### Tier 2: Framework Knowledge

```
Knowledge/
├── KNOWLEDGE_GRAPH.md            [This file - navigation map]
├── DOCUMENT_INDEX.md             [Topic-based quick lookup]
└── FRAMEWORK_DECISIONS.md        [Architectural decisions and rationale]
```

### Tier 3: Generated Artifacts

```
Generated/
├── PROGRESS_TRACKER.md           [Session continuity - current state]
├── Repos/                        [Converted repo profiles]
├── Analysis/                     [Repository analyses]
├── Reports/                      [Generated reports]
└── session_logs/                 [Session continuity logs]
```

### Tier 4: Templates and Prompts

```
prompts/templates/
├── AI Agents/                         [Full agent definitions - source of truth for agents]
│   ├── AGENTIC_REPOS_AI_AGENT.md      [Domain agent - primary session entry point]
│   ├── REPO_ONBOARDING_AGENT.md       [Generic repo onboarding agent]
│   └── README.md                      [How to use agents]
└── Universal/                         [Universal prompt templates]
```

---

## Concept Clusters

### Cluster 1: Framework Core

**Topic:** What is this framework and how does it work?

| Document                                         | Contents                                   | Authority     |
| ------------------------------------------------ | ------------------------------------------ | ------------- |
| `START_HERE.md`                                  | Framework overview, commands, architecture | High          |
| `CLAUDE.md`                                      | Rules for AI interactions                  | High          |
| `AGENTS.md`                                      | Claude Code workspace instructions         | High          |
| `Knowledge/Source of Truth/AGENTIC_FRAMEWORK.md` | Design principles                          | Authoritative |

**Key Questions:**

- What is Agentic-Repos? → `START_HERE.md`
- What rules govern AI responses? → `CLAUDE.md`
- How are agents organized? → `AGENTS.md` and `CLAUDE.md` Rule 7

---

### Cluster 2: Converting Repos

**Topic:** How to transform any repo into an agentic environment

| Document                                               | Contents                    | Authority |
| ------------------------------------------------------ | --------------------------- | --------- |
| `.claude/commands/convert-repo-to-agentic.md`          | Claude Code command         | High      |
| `.windsurf/workflows/convert-repo-to-agentic.md`       | Windsurf workflow           | High      |
| `prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md` | Full agent for onboarding   | High      |
| `Generated/Repos/*.md`                                 | Profiles of converted repos | Medium    |

**Key Questions:**

- How do I convert a repo? → `START_HERE.md` → Available Commands section
- What does the convert command do? → `.claude/commands/convert-repo-to-agentic.md`
- What gets created? → `START_HERE.md` → "What Gets Created" section
- How is the domain agent skill generated? → `REPO_ONBOARDING_AGENT.md` Step 10.6
- How does Jira sync work? → `REPO_ONBOARDING_AGENT.md` Step 10.6, domain agent skill template
- How is cross-workspace registration done? → `REPO_ONBOARDING_AGENT.md` Step 12.5

---

### Cluster 3: Agent Architecture

**Topic:** How agents are organized and created

| Document                                      | Contents                              | Authority |
| --------------------------------------------- | ------------------------------------- | --------- |
| `CLAUDE.md` Rule 7                            | Agent architecture pattern            | High      |
| `CLAUDE.md` Rule 13                           | How to create Claude Code agents      | High      |
| `prompts/templates/AI Agents/README.md`       | Agent catalog                         | High      |
| `.claude/skills/agentic-repos-agent/SKILL.md` | Domain AI skill (primary entry point) | High      |
| `.claude/agents/repo-analyzer.md`             | Deep repo analysis agent              | High      |
| `.claude/agents/knowledge-builder.md`         | Knowledge Graph builder agent         | High      |
| `.claude/agents/developer.md`                 | Framework development agent           | High      |
| `.claude/agents/researcher.md`                | Evidence-based research agent         | High      |
| `.claude/agents/code-reviewer.md`             | Code review agent                     | High      |
| `.claude/commands/*.md`                       | Slash command wrappers                | High      |

**Key Questions:**

- How are agents structured? → `CLAUDE.md` Rule 7
- How do I create a new agent? → `CLAUDE.md` Rule 13
- What agents are available? → `prompts/templates/AI Agents/README.md`

---

### Cluster 4: Knowledge Management

**Topic:** How knowledge is organized and navigated

| Document                      | Contents                         | Authority |
| ----------------------------- | -------------------------------- | --------- |
| This file                     | Navigation map                   | High      |
| `Knowledge/DOCUMENT_INDEX.md` | Topic lookup                     | High      |
| `CLAUDE.md` Rule 8            | Knowledge Graph navigation rules | High      |
| `CLAUDE.md` Rule 9            | Generated artifacts standard     | High      |

**Key Questions:**

- How is knowledge organized? → This file, Hierarchy section
- Where do AI artifacts go? → `CLAUDE.md` Rule 9

---

### Cluster 5: Evidence and Quality

**Topic:** Evidence-based development and zero hallucination

| Document                                         | Contents                   | Authority     |
| ------------------------------------------------ | -------------------------- | ------------- |
| `CLAUDE.md` Rules 1-6                            | Evidence rules and formats | Authoritative |
| `Knowledge/Source of Truth/AGENTIC_FRAMEWORK.md` | Design principles          | Authoritative |

**Key Questions:**

- How do I cite evidence? → `CLAUDE.md` Rule 1 and Rule 5
- What format for technical claims? → `CLAUDE.md` Rule 5 (CLAIM/SOURCE/CONFIDENCE)

---

## Search Index

| Keyword                | Find It In                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------- |
| activate               | `.claude/skills/agentic-repos-agent/SKILL.md`, `.claude/commands/agentic-repos-ai.md` |
| agent creation         | `CLAUDE.md` Rule 13                                                                   |
| agents                 | `prompts/templates/AI Agents/README.md`, `.claude/agents/`                            |
| commands               | `.claude/commands/`, `CLAUDE.md` Available Commands table                             |
| domain agent           | `prompts/templates/AI Agents/AGENTIC_REPOS_AI_AGENT.md`                               |
| confidence levels      | `CLAUDE.md` Rule 2                                                                    |
| convert repo           | `.claude/commands/convert-repo-to-agentic.md`                                         |
| evidence               | `CLAUDE.md` Rules 1, 5                                                                |
| generated artifacts    | `CLAUDE.md` Rule 9, `Generated/`                                                      |
| gitignore              | `.gitignore`                                                                          |
| hallucination          | `CLAUDE.md` Zero Hallucination Policy                                                 |
| knowledge graph        | This file                                                                             |
| rules                  | `CLAUDE.md`                                                                           |
| progress tracker       | `Generated/PROGRESS_TRACKER.md`                                                       |
| skill                  | `.claude/skills/agentic-repos-agent/SKILL.md`                                         |
| session entry point    | `.claude/skills/agentic-repos-agent/SKILL.md`, `.claude/commands/agentic-repos-ai.md` |
| session initialization | `CLAUDE.md` Rule 0                                                                    |
| session continuity     | `prompts/templates/AI Agents/README.md`                                               |
| source of truth        | `Knowledge/Source of Truth/`                                                          |
| tech stack detection   | `.claude/commands/convert-repo-to-agentic.md`                                         |
| workflows              | `.windsurf/workflows/`, `.claude/commands/`                                           |
| auth patterns          | `REPO_ONBOARDING_AGENT.md` Step 5.6                                                   |
| catalog-info           | `REPO_ONBOARDING_AGENT.md` Step 5.5                                                   |
| cross-workspace        | `REPO_ONBOARDING_AGENT.md` Step 12.5                                                  |
| jira sync              | `REPO_ONBOARDING_AGENT.md` Step 10.6 (domain agent skill)                             |
| sme contacts           | `REPO_ONBOARDING_AGENT.md` Step 10.7                                                  |
| zero hallucination     | `CLAUDE.md` Zero Hallucination Policy                                                 |

---

## New User Path

Follow in order:

1. `START_HERE.md` - What this framework does (5 min)
2. `CLAUDE.md` - Rules governing AI behavior (10 min)
3. `Knowledge/Source of Truth/AGENTIC_FRAMEWORK.md` - Design principles (10 min)
4. `.claude/commands/convert-repo-to-agentic.md` - The primary command (15 min)
5. Try converting a repo: `/project:convert-repo-to-agentic <any-repo>`

---

## Maintenance

When adding a new document:

1. Add it to the correct Tier above
2. Add to the relevant Concept Cluster
3. Add keywords to the Search Index
4. Update "Last Updated" timestamp
