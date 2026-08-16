---
description: "Pipeline lane. Creates a JIRA Story on a company GitLab repo and hands it to the Agentic SDLC pipeline. NO local branch or worktree -- the pipeline owns them. Monitors the MR and closes the ticket on merge. Team-agnostic: project binding read from BINDING.yml."
---

# /start-sdlc-feature -- the pipeline lane

Creates a JIRA Story, hands it to **the pipeline**, and watches it to completion. The pipeline writes the
code, creates its own `pipeline/...` branch, and authors the MR -- so the MR counts as **`is_agentic`**.

**Nothing is created on your disk.** No branch, no worktree, nothing to clean up afterwards.

> **Companion lane:** the **human** lane is the same repo class and the same ticket discipline,
> but _you_ write the code in a worktree and author the MR yourself. A hand-authored MR counts
> as `is_ai_assisted`, not `is_agentic`. Use the pipeline lane unless the pipeline genuinely cannot
> do the work.
>
> **Not for personal or GitHub repos.** the pipeline only operates on the company GitLab.

---

## CARDINAL RULE -- hands off git, entirely

Once this command labels the ticket, **you do not touch git for that repo.** No `git commit`, no
`git push`, no `glab mr create`, no `gh pr create` -- no matter how the request is phrased.

"Put it in the MR" / "add it to the same MR" always means **the pipeline MR**. To get specific
content in, add it to the ticket as a **spec comment**; the pipeline ingests amendments mid-run in about
60 seconds.

This rule exists because it was violated in practice (PROJ-2229 !4, PROJ-2368 !215). Teams can
enforce it mechanically with a Claude Code pre-tool hook that blocks git-write commands while a
The pipeline ticket is open on the repo.

## CARDINAL RULE -- the `agentic-sdlc` label is FOREVER

Never remove it. Not after merge, not on NOT-IMPLEMENTABLE, not on FAILED_STOP, **not on a no-op**.
Policy locked 2026-08-07; this voids the older carve-out that permitted removal for
"tickets that are not delivered agentic work." If a ticket can't be implemented, post the
acknowledgment and leave the label alone.

## CARDINAL RULE -- every ticket under your team's ACI-tied epic

Parent comes from `binding.epic` (Step C). Override with `--epic KEY-XXXX` only when the work
genuinely belongs elsewhere. Never leave a ticket without an epic parent -- it earns no rollup credit.

---

## Usage

```
/start-sdlc-feature <description>
/start-sdlc-feature --repo <path> <description>
/start-sdlc-feature --epic KEY-1234 <description>
```

## Configuration

**Platform defaults -- the same for every the company team. Do not put these in a project config.**

```yaml
jira_cloud_id: "your-org.atlassian.net"
jira_issue_type: "Story"
agentic_sdlc_label: "agentic-sdlc" # the pipeline trigger
sdlc_service_account: "the-pipeline-service-account" # the ONLY author that yields is_agentic
company_remote_marker: "your-org" # repo-class test
transition_in_progress_id: "21"
transition_done_id: "31"
customfield_story_points: "customfield_10003"
customfield_sprint: "customfield_10330" # NOT 10020
customfield_dev_classification: "customfield_30832"
```

**Project binding -- differs per team. Read at run time, NEVER hardcoded here.**

`jira_project` - `epic` - `board` - `dev_classification` - `assignee_account_id`

### Step C: resolve the project binding (before creating anything)

Look for **`BINDING.yml` at the root of the target repo**:

```bash
cat "$REPO/BINDING.yml"
```

```yaml
# BINDING.yml (example shape -- use YOUR team's values)
jira_project: ABC
epic: ABC-1234 # your team's ACI-monitored epic; update each sprint
board: 1234
dev_classification: Growth
assignee_account_id: "<jira-account-id-of-the-requester>"
```

**If `BINDING.yml` is missing, STOP and ASK.** Do not guess, and do not fall back to another
team's project or epic.

That fallback is the actual failure mode this file exists to prevent: a team runs this command in
their repo, the ticket silently lands in **another team's project under another team's epic**, and
it pollutes that team's velocity and Say/Do while the owning team never sees the work. Ask for the
five values, then offer to write `BINDING.yml` so the next run is clean.

`/convert-repo-to-agentic` creates `BINDING.yml` for newly converted repos, so this prompt should
only ever appear on a repo that predates it.

---

## Step 0: Repo class gate -- the company GitLab only

```bash
git -C "$REPO" remote get-url origin
```

- Contains `your-org` / `.your-org.io` -- **proceed.**
- `github.com` -- **STOP.** the pipeline does not operate there.
- No remote -- **STOP.** Nothing to open an MR against.

## Step 1: Repo preflight

The preflight script ships with the Agentic-Repos framework
(`scripts/sdlc_repo_preflight.py`; converted repos receive a copy):

```bash
python3 scripts/sdlc_repo_preflight.py --repo "<repo name or full path>"
```

**PASS** -- use the printed canonical full path in the ticket; never a bare name.

**FAIL** -- do not assume the repo is dead. The script authenticates through `glab`, and it reports
an **expired glab token identically to a missing project**. Control-test with `team_group` (it is
hardcoded as canonical): if _that_ fails too, the script's auth is broken, not the repo. Confirm
liveness directly instead, and say you verified by the alternate route rather than that preflight
passed:

```bash
G=$GITLAB_API_TOKEN   # any valid GitLab PAT, e.g. from the repo's .env
P=$(python3 -c "import urllib.parse;print(urllib.parse.quote('your-org/apps/GROUP/REPO',safe=''))")
curl -s -H "PRIVATE-TOKEN: $G" "https://gitlab.com/api/v4/projects/$P"
```

Check `archived`, `empty_repo`, `marked_for_deletion_on`, and `deletion_scheduled` in the path.
Only a genuine dead-repo result stops the handoff.

## Step 2: Create the ticket

Generate a summary (imperative, 80 chars or less) and a spec-quality description.

**Write the spec so the pipeline executes it well** -- this is the highest-leverage part of the command:

- **Acceptance criteria as runnable commands with expected output**, not intentions. An executable
  AC costs zero clarification rounds because the criterion _is_ the test.
- **State the outcome, not the artifact.** "Port these scripts" gets you files that don't run;
  "`/foo` completes end to end, exit 0" gets you a working feature.
- **Every path must resolve for the pipeline.** It runs elsewhere -- local absolute paths and OneDrive
  paths are dead to it. Reference `<group>/<repo>` + branch + repo-relative paths, and **inline any
  content it must reproduce verbatim.**
- **Full spec at trigger beats mid-flight amendment.** Amendment works (~60s ingestion) but measured
  worse on completeness: 3-of-5 sites fixed vs. 5-of-5.
- **Never split one file's work across two concurrent tickets** -- competing branches, and closing
  one has discarded reviewed code before.

```
createJiraIssue(cloudId, projectKey: <binding.jira_project>, issueTypeName: "Story",
                summary, description, contentFormat: "markdown",
                parent: <binding.epic>, assignee_account_id: <binding.assignee_account_id>,
                additional_fields: {"customfield_10003": <SP>,
                                    "customfield_30832": {"value": "<binding.dev_classification>"}})
```

**Never put spec content in a markdown blockquote.** JIRA's ADF conversion silently drops `>`
blocks -- HTTP 201, no warning, content gone. Use a fenced block and **read back the returned
`body`** to confirm it survived.

## Step 3: Sprint, worklog

Sprint is **not on the create screen** -- it is a second call. The field is `customfield_10330`
(not `10020`); the POST returns 204 either way, so verify by reading back.

```bash
# active sprint
curl -s -u "$E:$T" "https://your-org.atlassian.net/rest/agile/1.0/board/<binding.board>/sprint?state=active"
# add
curl -s -X POST -u "$E:$T" -H "Content-Type: application/json" \
  -d '{"issues":["KEY-XXXX"]}' "https://your-org.atlassian.net/rest/agile/1.0/sprint/<id>/issue"
```

**1m placeholder worklog** -- comment must be **ADF** on this endpoint (a plain string 400s):

```bash
curl -s -X POST -u "$E:$T" -H "Content-Type: application/json" \
  -d '{"timeSpent":"1m","comment":{"type":"doc","version":1,"content":[{"type":"paragraph",
       "content":[{"type":"text","text":"Placeholder worklog (1m). Real time booked at Done (SP x 1h)."}]}]}}' \
  "https://your-org.atlassian.net/rest/api/3/issue/KEY-XXXX/worklog"
```

A ticket is born with **parent epic + SP + Development Classification + 1m worklog**. All four.

## Step 4: Trigger the pipeline

Transition to In Progress (`21`), then **append** the label -- read existing labels first, never
overwrite:

```bash
curl -s -X PUT -u "$E:$T" -H "Content-Type: application/json" \
  -d '{"update":{"labels":[{"add":"agentic-sdlc"}]}}' \
  "https://your-org.atlassian.net/rest/api/3/issue/KEY-XXXX"
```

The pipeline picks it up within seconds and posts a run URL on the ticket.

## Step 5: NO worktree, NO branch -- deliberately

**Do not create either.** the pipeline works on its own `pipeline/key-XXXX-...` branch, which is a
sibling of anything you'd cut from `main` -- a local worktree could never show you the pipeline's
output, and stale worktrees accumulate because no MR ever matches the worktree's own branch.

To inspect the pipeline's work once the branch exists:

```bash
git -C "$REPO" fetch origin
git -C "$REPO" diff main origin/pipeline/key-XXXX-<slug>
```

## Step 6: Monitor to terminal state

Poll the ticket. Branch on the pipeline's comments:

| Signal                          | Action                                                                                                     |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Blocking spec question          | Answer from evidence and post immediately. Cite sources.                                                   |
| Owner/SME-blocked               | Name the owner, escalate to the repo owner (see CODEOWNERS), **pause** -- never fabricate the value        |
| FAILED_STOP / NOT IMPLEMENTABLE | Post an acknowledgment. **Keep the label.** Stop.                                                          |
| No-op                           | Same -- acknowledge, **keep the label**, close as delivered if the work already exists                     |
| MR created                      | Move to MR watch (Step 7)                                                                                  |
| Silent > 2h                     | Check the pipeline run status before waiting longer -- a hung run needs a platform escalation, not patience |

Cadence: ~270s while a pipeline runs; 1200-1800s when waiting on a human.

## Step 6.5: Track and answer ALL comments -- ticket AND MR (standing duty)

Watching for a terminal state is not enough. Both comment surfaces stay tracked until merge:

**JIRA ticket comments (the pipeline -> you):**

- A pipeline question / awaiting-human-answer state gets answered as a **spec comment** within the
  polling cadence. An unanswered question stalls the run silently.
- A FAILED run gets a retry spec comment ("spec unchanged and still valid -- please retry the
  standard-feature-flow from the top") -- never a label cycle.

**MR review threads (reviewers -> the branch):**

- Poll unresolved discussions on the pipeline MR. Review bots, human reviewers, and the pipeline's own
  review node all comment here.
- For EVERY unresolved thread: post the fix list as a **spec comment on the JIRA ticket** (exact
  path:line corrections -- the pipeline ingests in ~60s and amends its own MR), plus one short
  acknowledgment note on the MR so reviewers see it is queued.
- **NEVER push fixes directly, even one-line corrections** -- the cardinal rule holds. Threads
  resolve -> approval fires -> an armed auto-merge completes.
- If your team pre-authorized approve+automerge (standing grant), arm merge-when-pipeline-succeeds
  as soon as the MR opens. The repo's approval rules, a green pipeline, and pipeline HITL gates
  remain the surviving protections.

Between sessions this duty belongs to the standing monitor (the scheduled wave-monitor pipeline or
an /agentic-sdlc-monitor sweep) -- closing a laptop must not orphan the loop.

Proven live 2026-08-15: 13 evidence-cited review threads across 5 MRs answered this way in one
pass; every fix routed through the pipeline, zero hand-pushes.

## Step 7: On merge -- close the loop

When the MR merges:

1. **Verify the author is the service account** -- `the-pipeline-service-account`. If it isn't, the MR is not
   `is_agentic`; say so plainly rather than reporting a clean result.
2. **Transition to Done with the closing worklog in the same call.** The Done screen (`31`) requires
   time, and here the worklog comment must be a **plain string** -- ADF 400s on the transition
   endpoint. Opposite of Step 3. Both formats were hit live on 2026-08-03 and again on 2026-08-07.

```bash
curl -s -X POST -u "$E:$T" -H "Content-Type: application/json" \
  -d '{"transition":{"id":"31"},"update":{"worklog":[{"add":{"timeSpent":"<SP>h",
       "comment":"Closing worklog: SP x 1h. The pipeline authored the MR; merged as <sha>."}}]}}' \
  "https://your-org.atlassian.net/rest/api/3/issue/KEY-XXXX/transitions"
```

3. **Fast-forward the main clone** -- only if it is on the default branch and clean:

```bash
git -C "$REPO" pull --ff-only
```

If it is on a feature branch or dirty: **fetch only and flag it.** Never checkout, stash, merge, or
force -- that is how work gets lost.

4. **Leave the `agentic-sdlc` label in place.**

## Step 8: Report

```
SDLC feature complete

  JIRA:      KEY-XXXX -- <summary>   [Done]
  Binding:   <binding.jira_project> - epic <binding.epic> - board <binding.board>   (from BINDING.yml)
  Parent:    <binding.epic> - SP <n> - <binding.dev_classification> - <n>h logged
  MR:        !<iid> merged as <sha>   author: the-pipeline-service-account -> is_agentic
  Repo:      <full gitlab path>, main fast-forwarded
  Worktree:  none created (Pipeline lane)
```

---

## Error handling

- **Non-the company remote** -- stop at Step 0; the pipeline only operates on the company GitLab
- **Preflight FAIL** -- control-test first; a universal failure means the script's auth, not the repo
- **Sprint assignment fails** -- continue; report "add to sprint manually"
- **the pipeline fails to produce an MR** -- that is a platform blocker for the Agentic SDLC platform
  team (the pipeline platform team). Escalate it. **Do not hand-author an MR as a workaround** --
  it masks the platform bug and does not count as agentic. If the work must land by hand, that is a
  deliberate switch to the human lane, and its metric cost should be stated out loud.
