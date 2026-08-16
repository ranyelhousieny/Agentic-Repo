---
description: Convert a whole GitLab group into an agentic PROJECT — every repo converted per policy, plus a fleet registry, router index, and cross-repo graph strong enough to run multi-repo features through /start-sdlc-feature
---

# /create-agentic-project — Windsurf wrapper (thin pointer)

**This is a thin pointer.** The single source of truth is the agent prompt. Read it in full and
execute every phase it defines. Do NOT duplicate its content here.

## Source of Truth

```
prompts/templates/AI Agents/PROJECT_ONBOARDING_AGENT.md
```

> **Framework home (works from ANY directory).** The agent prompt and all fleet tooling live in the
> **agentic-repo checkout**, not in `$PROJECT_DIR`. Resolve it once and use it for every framework
> path below:
>
> ```bash
> FRAMEWORK_HOME=${FRAMEWORK_HOME:-$([ -f scripts/fleet/project_verify.py ] && echo . || echo ~/code/the company/agentic-repo)}
> ```

## Activation Steps

1. // turbo
   Run: `date '+%A, %B %d, %Y %H:%M %Z'`
2. // turbo
   Verify the framework ref BEFORE anything else — the gate is **tooling presence, not a branch
   name** (a hardcoded branch goes stale the day it merges and then reads as STOP on the very ref
   that carries the code):

   ```bash
   test -f "$FRAMEWORK_HOME/scripts/fleet/project_verify.py" \
     || { echo "FLEET TOOLING MISSING AT THIS REF -- STOP"; exit 1; }
   git -C "$FRAMEWORK_HOME" branch --show-current   # record it; Phase 3 names it in every spec
   ```

   If the tooling is absent, STOP and tell the user — never run this command from a ref that
   does not carry it.
3. Read the source agent prompt (path above) in full.
4. Execute its phases in order, exactly as written:
   - Phase 0 preflight (glab auth gate — STOP loudly on failure)
   - Phase 1 discovery (read-only; MEMBERS.yaml + DRIFT.md)
   - Phase 2 policy gate (HUMAN promotes; hard stop on proposals)
   - Phase 3 member conversions — ALL through the pipeline (/start-sdlc-feature per member, no local
     cloning; project ticket 0 immediately, closing aggregation ticket after the wave)
   - Phase 4 aggregation (remote-cache fetch for uncloned members, then fleet registry, project
     index, cross-repo graph)
   - Phase 5 project knowledge shell
   - Phase 6 verify (`scripts/fleet/project_verify.py` exit 0) and report
   - Phase 7 operating mode: big features → sequenced per-repo /start-sdlc-feature tickets
5. Enforce the agent prompt's Hard Rules 1–5, especially: read-only against member repos,
   discovery proposes / a standing authorization promotes, and the router stays a router.
   The approve+automerge grant is BOUNDED (scope, review date, read-the-diff, and a human read of
   every `BINDING.yml`) — see the agent prompt's "Autonomy + merge policy" section. A project
   copying this workflow does NOT inherit the grant; it records its own or runs with per-MR
   human approval.
6. **Standing duty — track every fired ticket's comments AND its MR review threads until merge**
   (agent prompt § Review-answer loop + /start-sdlc-feature Step 6.5): answer the pipeline questions as
   spec comments, route every review-thread fix through a spec comment on the ticket (never a
   direct push), retry failed runs by comment. Between sessions, hand the duty to the scheduled
   wave-monitor pipeline — a closed laptop must not orphan the loop.
