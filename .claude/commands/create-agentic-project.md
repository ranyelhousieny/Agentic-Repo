# Create Agentic Project

**Project-level counterpart of `/convert-repo-to-agentic`.** Converts every repo in a GitLab group
to an agentic repo (per human-approved policy) and aggregates a project knowledge layer — fleet
registry, router index, cross-repo graph, entity cards — strong enough to plan multi-repo features
and execute them through `/start-sdlc-feature` tickets alone.

**Idempotent / re-runnable.** Discovery, registry, index, and graph are regenerated in place;
human-owned files (`Source of Truth/`, `entities/` prose, policy edits in `MEMBERS.yaml`) are never
clobbered. Member conversions delegate to `/convert-repo-to-agentic`, which has its own UPDATE mode.

## Activation Steps

### Step 0: Date + framework ref (do this before anything)

// turbo
Run: `date '+%A, %B %d, %Y %H:%M %Z'`

```bash
git branch --show-current   # must print: integration/weekend-final (main only AFTER the weekend merge)
test -f scripts/fleet/project_verify.py && echo "fleet tooling present" || echo "STOP: fleet tooling missing at this ref"
```

If the branch is wrong or the tooling is missing, STOP and tell the user. Never fall back to main
before the weekend branch has merged.

### Step 1: Read the full agent prompt

Read: `prompts/templates/AI Agents/PROJECT_ONBOARDING_AGENT.md`

Adopt the role and execute all phases defined there:

- Phase 0: Preflight (glab auth gate — an expired token reads as an empty group; STOP loudly)
- Phase 1: Discovery (`scripts/fleet/discover_members.py` → MEMBERS.yaml + Generated/DRIFT.md)
- Phase 2: Policy gate — HUMAN promotes policies; never proceed on proposals
- Phase 3: Member conversions — ALL through the pipeline (`/start-sdlc-feature` ticket per member, no
  local cloning; ticket 0 = project layer immediately, closing ticket = aggregation refresh after
  the wave merges)
- Phase 4: Aggregation (`build_fleet_registry.py`, `build_project_index.py`,
  `build_cross_repo_graph.py`)
- Phase 5: Project knowledge shell (CLAUDE.md, entities/, Source of Truth, TEAM.md, BINDING.yml)
- Phase 6: Verify and report
- Phase 7: OPERATING MODE — big features decomposed along the cross-repo graph into sequenced
  per-repo `/start-sdlc-feature` tickets (one ticket = one repo; providers before consumers;
  hands off git)

### Step 2: Get inputs from the user

- `$GROUP` — GitLab group path (e.g. `your-org/apps/<group>`)
- `$PROJECT_DIR` — the project-layer directory (existing project repo or new dir)
- `$ROOTS` — local clone roots to scan

### Step 3: Verify (mechanical gate)

// turbo

```bash
python3 "$FRAMEWORK_HOME/scripts/fleet/project_verify.py" "$PROJECT_DIR" --require-binding
```

Exit 1 = incomplete — the table names exactly what is missing; fix before reporting.

### Step 4: Present the completion report

Use the report shape defined at the bottom of the agent prompt. Every number from this run's
artifacts; none from memory.

### Step 5: Enforce the standing rules

- Enforce the agent prompt's Hard Rules 1–5, especially: read-only against member repos,
  discovery proposes / a standing authorization promotes, and the router stays a router.
- **Standing duty — track every fired ticket's comments AND its MR review threads until merge**
  (agent prompt § Review-answer loop + /start-sdlc-feature Step 6.5): answer the pipeline questions as
  spec comments, route every review-thread fix through a spec comment on the ticket (never a
  direct push), retry failed runs by comment. Between sessions, hand the duty to the scheduled
  wave-monitor pipeline — a closed laptop must not orphan the loop.
