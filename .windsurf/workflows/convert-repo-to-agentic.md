---
description: Transform any repository into a full agentic development environment. Provide a GitLab URL or local path. Creates CLAUDE.md, AGENTS.md, START_HERE.md, Knowledge Graph, and specialized AI agents tailored to the detected tech stack.
---

# Convert Repo to Agentic

**Primary workflow for the Agentic-Repos framework.**

Transforms any repository into an AI-powered development environment with the same architecture as a production platform team.

**♻️ Idempotent / re-runnable.** If the target repo already has agentic content (`CLAUDE.md`, `Knowledge/`, `START_HERE.md`, `.claude/skills/<repo>-agent/`, or a domain agent), this workflow runs in **UPDATE mode** — it merges/refreshes in place (additively) rather than overwriting or duplicating: an existing `CLAUDE.md` gets the Session-Init pointer injected (never clobbered), Source of Truth is preserved, and only missing artifacts are added. Safe to run repeatedly. Details: Step 4 delegates to `prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md` → Phase 2 "UPDATE MODE".

## Activation Steps

### Step 0: Get today's date

// turbo
Run: `date '+%A, %B %d, %Y %H:%M %Z'`
Store as `$TODAY`.

### Step 1: Read framework context

1. Read `START_HERE.md`
2. Read `Knowledge/KNOWLEDGE_GRAPH.md`

### Step 2: Get target repo from user

Ask: "What repository do you want to convert? (GitLab URL or local path)"

Parse:

- `$REPO_PATH` = absolute path (clone target if URL)
- `$REPO_NAME` = directory name
- `$REPO_URL` = original URL (if provided)

### Step 3: Clone if needed

If a URL was provided:

```bash
# Full clone — do NOT use --depth 1 (history is required for T1 ownership derivation:
# git shortlog, recent-window shortlog, and JIRA-key frequency all need full history).
# Do NOT use --filter=blob:none (measured larger on small-blob repos).
git clone $REPO_URL /tmp/$REPO_NAME
export REPO_PATH=/tmp/$REPO_NAME
```

If a local path was provided:

```bash
ls $REPO_PATH/
```

### Step 4: Read the full agent prompt

Read: `prompts/templates/AI Agents/REPO_ONBOARDING_AGENT.md`

Adopt the role and execute all phases defined there:

- Phase 1: Discovery
- Phase 1.5: Code Index + Dependency Graph (Graphify engine — AUTO-INSTALLS via
  `scripts/onboarding/ensure_graphify.sh`; do NOT skip. A skip is legitimate only
  when the script proves installation impossible (rc 3: no python >= 3.10, offline
  pip) and it is loud: log + console + completion report all carry the reason)
- Phase 2: Generate all artifacts
- Phase 3: Create Progress Tracker
- Phase 4: Register in Agentic-Repos
- Phase 5: Verify and report

### Step 5: Verify all files created (mechanical gate)

// turbo

```bash
# Everything-created gate (Step 15.8 of the agent prompt): required files
# non-empty, domain-agent globs match, either-or contracts hold (CODEOWNERS |
# CODEOWNERS.proposed; CODE_GRAPH.jsonl | GRAPHIFY_BOOTSTRAP.err |
# GRAPHIFY_SKIPPED | GRAPHIFY_NO_EDGES; golden facts | GOLDEN_FACTS_NONE.md), CODE_INDEX
# registered everywhere, no unexpanded placeholders. Exit 1 = conversion
# incomplete — the table names exactly what is missing; fix before Step 6.
python3 "$FRAMEWORK_HOME/scripts/onboarding/final_verify.py" "$REPO_PATH"
```

### Step 6: Present completion report

Report to user:

```
Conversion Complete: $REPO_NAME

Stack: [detected tech stack]
Endpoints Found: [count]
Auth Pattern: [detected pattern]
Dependency Graph: [graphifyy==<version>, N records, M edges | NONE — <reason from whichever marker is present under Generated/Analysis/: GRAPHIFY_BOOTSTRAP.err (install failed), GRAPHIFY_SKIPPED (operator kill switch), GRAPHIFY_NO_EDGES (clean run, no edges resolved)>]
Golden Facts: [N/N hold (Step 15.7 gate) | NONE DERIVABLE — see Knowledge/golden/GOLDEN_FACTS_NONE.md, an L5 gap not a failure | MISSING — derive failed, see stderr]
Final Verify: [N/N checks pass (Step 5 gate)]
CODEOWNERS: [proposed — review, rename, commit | already governed | not derivable — <reason>]

Files Created:
  Domain Agent (START EVERY SESSION HERE):
    .claude/skills/<repo>-agent/SKILL.md           (@<repo>-agent, item 4 of the CLAUDE.md Session-Init block)
    prompts/templates/AI Agents/<REPO>_AI_AGENT.md (domain agent source of truth)
    .claude/commands/<repo>-ai.md                  (/project:<repo>-ai)
  CLAUDE.md, AGENTS.md, START_HERE.md
  Knowledge/ (Knowledge Graph, Document Index, Source of Truth template, SME_CONTACTS)
  Generated/PROGRESS_TRACKER.md
  .claude/agents/ (developer, researcher, code-reviewer)
  .claude/commands/ (<repo>-ai, code-review, generate-session-context, analyze-repo)

Next Steps:
  1. Open $REPO_PATH in Claude Code (CLAUDE.md + AGENTS.md auto-load)
  2. Activate the domain agent: @<repo>-agent  OR  /project:<repo>-ai  (start every session here)
  3. Fill in Knowledge/Source of Truth/PROJECT_VISION.md with your team
  4. Run /project:code-review to see agents in action
  5. Commit the agentic framework files: git add -A && git commit -m "feat: add agentic development framework"
```
