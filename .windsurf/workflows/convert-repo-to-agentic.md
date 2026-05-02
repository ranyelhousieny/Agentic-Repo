---
description: Transform any repository into a full agentic development environment. Provide a GitHub/GitLab URL or local path. Creates CLAUDE.md, AGENTS.md, START_HERE.md, Knowledge Graph, and specialized AI agents tailored to the detected tech stack.
---

# Convert Repo to Agentic

**Primary workflow for the Agentic-Repos framework.**

Transforms any repository into an AI-powered development environment with battle-tested architecture for evidence-based knowledge management.

## Activation Steps

### Step 0: Get today's date
// turbo
Run: `date '+%A, %B %d, %Y %H:%M %Z'`
Store as `$TODAY`.

### Step 1: Read framework context
1. Read `START_HERE.md`
2. Read `Knowledge/KNOWLEDGE_GRAPH.md`

### Step 2: Get target repo from user

Ask: "What repository do you want to convert? (GitHub/GitLab URL or local path)"

Parse:
- `$REPO_PATH` = absolute path (clone target if URL)
- `$REPO_NAME` = directory name
- `$REPO_URL` = original URL (if provided)

### Step 3: Clone if needed

If a URL was provided:
```bash
git clone --depth 1 $REPO_URL /tmp/$REPO_NAME
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
- Phase 2: Generate all artifacts
- Phase 3: Create Progress Tracker
- Phase 4: Register in Agentic-Repos
- Phase 5: Verify and report

### Step 5: Verify all files created

// turbo
```bash
echo "=== Core Files ===" && ls -la $REPO_PATH/CLAUDE.md $REPO_PATH/AGENTS.md $REPO_PATH/START_HERE.md 2>/dev/null
echo "=== Knowledge ===" && ls -la $REPO_PATH/Knowledge/ 2>/dev/null
echo "=== Claude Code ===" && ls -la $REPO_PATH/.claude/ 2>/dev/null
echo "=== Generated ===" && ls -la $REPO_PATH/Generated/ 2>/dev/null
```

### Step 6: Present completion report

Report to user:
```
Conversion Complete: $REPO_NAME

Stack: [detected tech stack]
Endpoints Found: [count]
Auth Pattern: [detected pattern]

Files Created:
  CLAUDE.md, AGENTS.md, START_HERE.md
  Knowledge/ (Knowledge Graph, Document Index, Source of Truth template)
  Generated/PROGRESS_TRACKER.md
  .claude/agents/ (developer, researcher, code-reviewer)
  .claude/commands/ (code-review, generate-session-context, analyze-repo)

Next Steps:
  1. Open $REPO_PATH in Claude Code (CLAUDE.md + AGENTS.md auto-load)
  2. Fill in Knowledge/Source of Truth/PROJECT_VISION.md with your team
  3. Run /project:code-review to see agents in action
  4. Commit the agentic framework files: git add -A && git commit -m "feat: add agentic development framework"
```
