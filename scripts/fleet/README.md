# scripts/fleet — the PROJECT (multi-repo) knowledge layer

Tooling behind `/create-agentic-project` (agent prompt:
`prompts/templates/AI Agents/PROJECT_ONBOARDING_AGENT.md`). The repo-level counterpart is
`scripts/onboarding/`. Division of labor: a member repo owns its own knowledge
(`/convert-repo-to-agentic`); this layer owns ONLY what no single repo can see — the roster, the
router, and the edges BETWEEN repos — and it points at member knowledge instead of copying it.

All scripts are stdlib-only, Python 3.9+, READ-ONLY against member repos, and fail loud: absent
artifacts render as `--`, auth failures stop the run, near-miss graph edges go to a sidecar for
human promotion instead of being invented or dropped.

| Script | Writes (into the project dir only) | Purpose |
|---|---|---|
| `discover_members.py` | `MEMBERS.yaml`, `Generated/DRIFT.md` | Group roster via authenticated API (subgroups included, auth preflighted, liveness by API — never batch SSH ls-remote, which trips rate limits and reads live repos as dead; measured 2026-08-15: 50 false positives dropped to 2 real 404s). Every member starts `policy: observe`; a human promotes. |
| `fetch_member_artifacts.py` | `Generated/remote_cache/<slug>/…`, `_meta.json` | Remote read cache for members with no local clone — the normal case in the Maestro lane, where conversions land on GitLab and are never cloned here. Fixed small artifact set from the member's DEFAULT branch over the authenticated API, SHA-gated (unchanged head = no refetch). A 404 is recorded as `absent`; any other API error marks the member UNVERIFIED and leaves the previous cache intact. Run it FIRST in Phase 4 — skipping it makes every uncloned member an all-`--` row. |
| `build_fleet_registry.py` | `Generated/FLEET_REGISTRY.md`, `.jsonl` | One measured row per member: readiness level, CODE_INDEX size, code-graph edges, golden facts, gate rate (with its scope), freshness (STALE = git moved past the member's KG date). Reads local clone first, remote cache second; cache-sourced rows say `(cache)`. |
| `build_project_index.py` | `PROJECT_INDEX.md` | The router. One line per member pointing at the member's own KG. Hard size cap enforced by the verifier — inlining member knowledge is the failure this file exists to prevent. |
| `build_cross_repo_graph.py` | `Generated/CROSS_REPO_GRAPH.jsonl`, `ARCHITECTURE_MAP.md`, `CROSS_REPO_NEEDS_VERIFICATION.jsonl` | Edges between members: `code-import` (EXTRACTED, from member CODE_GRAPHs vs sibling publish aliases), `iac-pair` (PATTERN, `X`/`X-iac` + tf evidence), `config-ref` (PATTERN, bounded config scan with a gitlab-namespace guard). Every edge: resolver, confidence, `file:line`. |
| `project_verify.py` | nothing (exit code) | The everything-created gate (R1–R8): roster, drift, registry row-count consistency, router present + under cap, graph + map present, shell files, `BINDING.yml` with **no `TODO` field left** (`--require-binding`), placeholder scan. Exit 0 or a table of exactly what is missing. |
| `fleetlib.py` | — | Shared parsers. Reads ONLY shapes our own writers emit; not a general YAML parser. |

Tests: `tests/test_fleet.py` (synthetic 4-member project; no network, no git binary dependence);
`tests/test_interpreter_floor.py`, which ENFORCES the 3.9 floor claimed above over `scripts/fleet/*.py`
plus `scripts/maestro_repo_preflight.py` — the two sweeps that already existed are scoped to
`scripts/onboarding/` and `scripts/eval/`, so this directory was outside both; and
`tests/test_step_c_binding_snippet.py`, which EXTRACTS the `BINDING.yml` check out of
`/start-sdlc-feature` Step C (it is a fenced heredoc in markdown, so nothing ran it) and executes it,
including a differential test asserting it agrees with `project_verify.binding_gaps()` — the two are
one rule in two implementations, and two copies that nothing compares will drift.
Run: `uv run --with pytest pytest scripts/fleet/tests/ scripts/tests/ -q`

Big-feature lane: after conversion, Phase 7 of the agent prompt decomposes a multi-repo feature
along the cross-repo graph into sequenced per-repo `/start-sdlc-feature` tickets (one ticket = one
repo, providers before consumers, hands off git).
