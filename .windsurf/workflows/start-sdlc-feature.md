---
description: Pipeline lane. Creates a JIRA Story on a company GitLab repo and hands it to the Agentic SDLC pipeline. NO local branch or worktree -- the pipeline owns them. Monitors the MR and closes the ticket on merge. Team-agnostic: project binding read from BINDING.yml.
---

# /start-sdlc-feature -- Windsurf wrapper (thin pointer)

**This is a thin pointer.** The single source of truth is the agent prompt. Read it in full and
execute every step it defines. Do NOT duplicate its content here (`CLAUDE.md` Rule 7).

## Source of Truth

```
prompts/templates/AI Agents/SDLC_FEATURE_AGENT.md
```

> **Framework home (works from ANY directory).** The agent prompt and
> `scripts/sdlc_repo_preflight.py` live in the **agentic-repo checkout**, not in the target repo.
> Resolve it once and use it for every framework path:
>
> ```bash
> FRAMEWORK_HOME=${FRAMEWORK_HOME:-$([ -f scripts/sdlc_repo_preflight.py ] && echo . || echo ~/code/the company/agentic-repo)}
> ```
>
> (Clone `git@gitlab.com:your-org/agentic-repo.git` there if missing; adjust
> if you cloned elsewhere.) `$REPO` is the **target** repo the story is for.

## Usage

```
/start-sdlc-feature <description>
/start-sdlc-feature --repo <path> <description>
/start-sdlc-feature --epic KEY-1234 <description>
```

## Activation Steps

1. // turbo
   Run: `date '+%A, %B %d, %Y %H:%M %Z'`
2. Read the source agent prompt (path above) in full and adopt the role.
3. Execute its steps in order, exactly as written:
   - Step C: resolve the project binding from `$REPO/BINDING.yml` -- **a missing file OR any
     `TODO` value is a hard STOP**, never a fallback to another team's project or epic
   - Step 0: repo class gate (the company GitLab only)
   - Step 1: repo preflight (`$FRAMEWORK_HOME/scripts/sdlc_repo_preflight.py`)
   - Steps 2-4: create the ticket, sprint + worklog, trigger the pipeline
   - Step 5: NO worktree, NO branch -- deliberately
   - Steps 6 and 6.5: monitor to a terminal state, and track/answer ALL comments -- ticket AND MR
   - Step 7: on merge, close the loop; Step 8: report
4. Enforce both CARDINAL RULES for the whole life of the ticket: **hands off git entirely** on that
   repo, and the **`agentic-sdlc` label is forever**.
