# scripts/onboarding — Code-Index Extraction Scripts

These scripts are invoked by `REPO_ONBOARDING_AGENT.md` during **Phase 1.5: Code Index**
to build a citation-backed inventory of a target repository.
They are NOT meant to be run directly in most cases — the onboarding agent orchestrates them.

---

## Interpreter Floor (minimum versions — source of truth for this directory)

**All scripts in `scripts/onboarding/` require:**

```
bash 3.2+, python3 3.9+
```

Every `# Requires:` header in each `.sh` and `.py` file in this directory mirrors this
floor verbatim.  Python 3.9 is the declared minimum because:

- It is the oldest interpreter known to be in active use on operator machines (verified:
  `/usr/bin/python3 -V` → `Python 3.9.6` on the AC4 regression target).
- `dict |` merge (PEP 584) and `str.removeprefix`/`removesuffix` (PEP 616) require 3.9 —
  both are safe to use at or above the floor.
- PEP 604 union-type annotations (`X | Y`) require **Python 3.10+** and are therefore
  **forbidden** in this directory.  Use `typing.Optional[X]` instead (PEP 484).
- Python 3.8 is not a supported target; no operator machine is known to run it.

Bash 3.2 compatibility is already enforced (B15) — the `# Requires: bash 3.2+` note on
each script documents and locks that guarantee.

**Sweep results (PROJ-2574):** `git grep -nE '\| *None|None *\|' scripts/onboarding/`
returned exactly one hit prior to this fix (`verify_citations.sh:311`), resolved in the
shipped scripts. Running the same sweep today returns 8 hits, none of them a regression:
1 is this README line's own self-reference to the grep pattern, and 7 are in
`tests/test_min_interpreter_smoke.py` — 2 real `str | None` return annotations (the
test's own interpreter-discovery helpers, which run on the developer interpreter, never
the 3.9 floor) plus 5 prose/comment/canary-string mentions of `Path | None` documenting
the historical defect. The ban is pinned by `tests/test_min_interpreter_smoke.py::test_no_pep604_union_in_py_scripts`,
which walks annotation ASTs rather than compiling: every `.py` script here carries
`from __future__ import annotations`, so a PEP-604 union compiles and runs fine on 3.9 and
the `py_compile` sweep below cannot see it — which is how three of them re-entered
`extract_fastapi.py` after this sweep declared the directory clean. The pin covers the
shipped `scripts/onboarding/*.py`; `tests/` is out of scope and does carry two (they run
on the developer interpreter, never on the 3.9 floor).
`git grep -nE '^\s*match .*:$' scripts/onboarding/*.py scripts/onboarding/*.sh` — 0 hits.
`git grep -nE 'declare -A|mapfile|readarray|\$\{[a-zA-Z_]+,,\}' scripts/onboarding/` — 0 hits
(two results in `extract_express.sh` comments documenting what NOT to use — not live code).

---

## Contract Overview

This directory contains **two distinct families** of scripts with **different stdout schemas**.
Do not mix them up.

| Family | Scripts | Schema |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Code-symbol extractors | `extract_spring_boot.sh`, `extract_fastapi.py`, `extract_express.sh`, `extract_terraform.sh` | `{path, line, kind, identifier}` — one record per symbol |
| Optional engine adapter (runs only when the engine is installed) | `extract_graphify.py`                                                                        | Same `{path, line, kind, identifier}` contract + additive `{engine, confidence}` fields   |
| Ownership extractor | `extract_git_ownership.sh` | `{area, top_committers, last_touched_date, commit_count}` — one record per top-level area |

---

## Code-Symbol Extractor CLI Contract

The four code-symbol extractors write **JSON-lines** to stdout.
Each line is one record:

```json
{"path":"<relative-path>","line":<int>,"kind":"<kind>","identifier":"<identifier>"}
```

| Field | Type | Description |
| ------------ | ------- | ---------------------------------- |
| `path` | string | File path relative to `$REPO_PATH` |
| `line` | integer | 1-based line number of the symbol |
| `kind` | string | One of the values below |
| `identifier` | string | Human-readable name / label |

### `kind` values (code-symbol extractors only)

| Kind | Meaning |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `module` | Top-level package, Maven module, or directory boundary |
| `entry_point` | Application entry point (main class, `FastAPI()`, etc.) |
| `endpoint` | HTTP/RPC endpoint or CLI command |
| `config` | Config key or env-var (`@Value`, `process.env.KEY`, `var.name`) |
| `integration` | External dependency / integration point |
| `test_location` | Test file or test directory root |
| `handler`       | Function/method symbol (optional Graphify adapter only)                                                                                                                                                        |
| `dependency`    | Import/call edge, identifier `"src -> dst"` (optional Graphify adapter only; written to `Generated/graphify/CODE_GRAPH.jsonl`, never stdout — keeps the eager-loaded index inside the activation token budget) |

**Additive fields:** the optional adapter appends `engine` (e.g. `graphifyy==0.9.43`) and
`confidence` (`EXTRACTED`) to each record. Consumers of the contract MUST ignore unknown
fields — the four base fields are the contract; everything else is provenance.

**Fail-closed guarantee:** an extractor that cannot produce a `path:line` citation
MUST drop the entry silently (never emit an entry with empty `path` or `line <= 0`).
This binds the optional adapter too: `extract_graphify.py` drops any node or edge whose
line number it cannot resolve rather than defaulting it to line 1.

**JSON safety:** All four code-symbol extractors delegate serialization to
`python3 json.dumps` rather than `printf`. This ensures that identifiers
containing `"`, `\`, or `%` (route paths, package names, annotation values)
never produce invalid JSON or cause `printf` format-specifier injection.

---

## Ownership Extractor CLI Contract

`extract_git_ownership.sh` emits a **different** JSON-lines schema (T1 v2):

```json
{
  "area": "<top-level-dir>",
  "original_architect": "Name <email>",
  "current_maintainer": "Name <email>",
  "codeowners_entry": "<CODEOWNERS match or null>",
  "catalog_info_owner": "<catalog-info.yaml spec.owner or null>",
  "agreement": "AGREE|CONFLICTING|SINGLE_SOURCE",
  "derivation_date": "YYYY-MM-DD",
  "top_committers": ["Name <email>", ...],
  "last_touched_date": "YYYY-MM-DD",
  "commit_count": <int>
}
```

| Field | Type | Description |
| -------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------- |
| `area` | string | Top-level directory name (e.g. `"src"`, `"tests"`, `"."` for root) |
| `original_architect` | string or null | All-time most-active committer in the area (bot-filtered) |
| `current_maintainer` | string or null | Most recent committer in the window (bot-filtered) |
| `codeowners_entry` | string or null | Matching CODEOWNERS entry for this area (null if no CODEOWNERS file) |
| `catalog_info_owner` | string or null | `spec.owner` from `catalog-info.yaml` (null if not present) |
| `agreement` | string | `AGREE` — git and static sources match; `CONFLICTING` — they disagree; `SINGLE_SOURCE` — only git history available |
| `derivation_date` | string | ISO-8601 date the record was derived |
| `top_committers` | array of strings | Up to 3 most-active human committers in the window, `"Name <email>"` format |
| `last_touched_date` | string | ISO-8601 date of the most recent commit in the window |
| `commit_count` | integer | Total **human** (bot-filtered) commits in the window for this area |

**Bot filtering:** Reads `scripts/onboarding/bot_identities.txt`. Bots are excluded from
`top_committers`, `original_architect`, `current_maintainer`, and `commit_count`. Areas
where ALL commits are from bots are SILENTLY DROPPED (fail-closed).

This script is consumed by `merge_sme_contacts.py`, NOT by the CODE_INDEX.md build step.

---

## Scripts

### `extract_fastapi.py` (code-symbol extractor)

```bash
python3 scripts/onboarding/extract_fastapi.py <REPO_PATH>
```

Uses Python's `ast` module (with regex fallback) to detect FastAPI/Flask route decorators,
`os.getenv()` calls, Pydantic `BaseSettings` fields, `httpx`/`requests`/`aiohttp` calls,
and test files (`test_*.py` / `*_test.py`).

**Fail-closed guard:** `emit()` checks `isinstance(line, int) and line > 0` — never passes
`str(0)` or `None` as a valid line number.

**Route decorators are gated on path shape, not on the verb.** `@x.get/post/patch/...` is
not a route unless its path argument is "/"-rooted (Starlette's `Route.__init__` and
Werkzeug's `Rule` both require that at runtime) — otherwise the receiver has to be a name
the module itself binds. Without the shape gate, 110 of 254 endpoint rows on a real FastAPI
monorepo carried PATCH against 2 genuine PATCH routes: 108 `@mock.patch("dotted.python.path")`
decorators in tests/ parse identically to a route. Both signals are needed, not either alone
— the shape gate keeps a route on an imported router (28 genuine routes on that same repo),
and the receiver gate keeps one whose path is a constant or a factory-bound `app`.

**Residual — shape is not provenance.** `@mock.patch("/absolute/looking/target")` passes the
shape gate and would be indexed as a route. Closing it means resolving `mock` across module
boundaries to prove it is not a route object, which this extractor does not do; 0 instances
across the five real Python services measured.

**Fallback:** when `ast.parse` raises `SyntaxError` or `OSError`, the script falls back to
a regex pass over the same `source` string (which is always initialized to `""` before the
try-block, so it is always bound).

**Requires:** `python3 3.9+`

---

### `extract_express.sh` (code-symbol extractor)

```bash
bash scripts/onboarding/extract_express.sh <REPO_PATH> [SRC_ROOTS...]
```

Detects Express/NestJS route handlers (`router.get(...)`, `@Get(...)`), `process.env.KEY`
references, `.env` file keys, `axios`/`fetch`/`got` integration calls, and spec/test files.

**Source root detection (B16):** If no `src/` directory exists, the extractor falls back to
scanning `$REPO_PATH` root with `node_modules/build/dist/target` excluded. Explicit
`SRC_ROOTS` can be passed as extra arguments (from `PHASE1_DETECTION.md Step 3.5`).

**Bash 3.2 compatibility (B15):** Uses `tr` instead of `${var,,}`, `while-read` instead of
`mapfile/readarray`, no associative arrays.

**Requires:** `bash 3.2+`, `grep`, `find`, `python3 3.9+`

---

### `extract_spring_boot.sh` (code-symbol extractor)

```bash
bash scripts/onboarding/extract_spring_boot.sh <REPO_PATH> [SRC_ROOTS...]
```

Detects Spring Boot endpoints (`@GetMapping` etc. — NOT `@RequestMapping` at class level,
which would produce phantom endpoint rows), `@Value` / `@ConfigurationProperties`,
`@FeignClient`, `RestTemplate`, `WebClient`, Kafka/Rabbit listeners, and test classes.

Class-level `@RequestMapping` is captured as a `config` record (base-path), not an endpoint.

**Source root detection (B16):** Falls back to scanning `$REPO_PATH` when no `src/` exists.
Explicit `SRC_ROOTS` can be passed (from `PHASE1_DETECTION.md Step 3.5`).

**Requires:** `bash 3.2+`, `grep`, `find`, `sed`, `awk`, `python3 3.9+`

---

### `extract_terraform.sh` (code-symbol extractor)

```bash
bash scripts/onboarding/extract_terraform.sh <REPO_PATH>
```

Detects Terraform `module`, `variable`, `provider`, `data`, `output` blocks, and
API Gateway / Lambda URL resource blocks.
Test locations: `.tftest.hcl` and Terratest `*_test.go` files.

**Requires:** `bash 3.2+`, `grep`, `find`, `python3 3.9+`

---

### `extract_graphify.py` (optional engine adapter — runs when the engine is installed)

```bash
python3 scripts/onboarding/extract_graphify.py <REPO_PATH>          # runs if graphifyy is installed in a 3.10+ interpreter
GRAPHIFY_ADAPTER=0 python3 scripts/onboarding/extract_graphify.py <REPO_PATH>   # kill switch
GRAPHIFY_PYTHON=python3.13 python3 scripts/onboarding/extract_graphify.py <REPO_PATH>   # name the engine's interpreter
```

Runs the `graphifyy` code-graph pass (deterministic tree-sitter AST — no LLM, no network)
and maps its `graph.json` into the code-symbol contract. The engine is a **tenant behind
the contract, never load-bearing**:

- **Gated on installation, with a fail-closed kill switch.** The engine is a pip package
  nobody has by default, so installing it is the opt-in. `GRAPHIFY_ADAPTER` disables the
  adapter for any value that is not an explicit affirmative (`1`/`true`/`yes`/`on`), so
  `GRAPHIFY_ADAPTER=disabled` and any typo stop the engine rather than silently running it.
  Removal drill: set the kill switch or uninstall the engine, and the framework degrades to
  the extractors above.
- **Preflight:** the engine requires Python **>= 3.10**, and that floor is checked against
  the interpreter that will actually RUN it — not against the one running this adapter.
  The two can differ: this adapter is documented above as runnable under bare `python3`,
  which on a stock macOS box is 3.9.6 (the floor this directory declares), so checking the
  adapter's own interpreter made the feature unreachable that way. Phase 1.5 itself no
  longer takes that route — since `ensure_graphify.sh` landed it runs the adapter under the
  interpreter that script resolves, which can import the engine and is therefore already
  3.10+. Resolution order is `GRAPHIFY_PYTHON`, else the adapter's own interpreter
  when it already meets the floor, else a probe of `python3.13`…`python3.10` on `PATH`. Only
  when none of those yields a 3.10+ interpreter does the adapter state the floor, name what
  it probed, and skip cleanly. It then requires `graphifyy >= 0.9.24` installed **in that
  interpreter** (`python3.13 -m pip install 'graphifyy==0.9.43'`, note the double `y`);
  absent or too old → clean skip with a loud stderr note. The version floor is a known-good
  schema baseline, not a pin — the mapper is verified against `0.9.43` and tolerates
  additive drift. When a `GRAPHIFY_CMD` override is honoured (see the env knobs below) the
  operator has named their own engine, so the distribution floor is skipped and provenance
  is stamped from `GRAPHIFY_ENGINE_ID` (default `graphifyy==unknown`).
- **Code-only invocation — this is the egress guarantee, and it is GATED.** The adapter
  calls only the engine's `update` subcommand ("re-extract code files and update the graph
  (no LLM needed)" per the engine help) with `--no-cluster`. The LLM-dependent paths
  (`extract`, community labeling) are not invoked. Because the guarantee is made of exactly
  those two values, `GRAPHIFY_SUBCOMMAND` and `GRAPHIFY_ARGS` are **ignored unless
  `GRAPHIFY_ALLOW_LLM_PATH=1` is explicitly set** — otherwise the whole safety posture sat
  one ungated env var away from false while the invocation log still announced the
  code-only path. When the gate is set the run is logged as `OVERRIDDEN` and the log
  withdraws the code-only claim for that run rather than asserting it.
- **Credential stripping — defence in depth, not the guarantee.** The subprocess env has
  every provider prefix (`OPENAI_`, `ANTHROPIC_`, `AWS_`, ...), every credential-shaped
  suffix (`*_API_KEY`, `*_BASE_URL`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_PASSWD`,
  `*_KEY`, `*_PAT`, `*_CREDENTIALS`, any case) and an exact denylist removed — the
  denylist covers `SSH_AUTH_SOCK` (a live ssh-agent socket: an active authentication
  channel, not just a readable secret), the proxy redirectors
  (`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`), `NETRC` and bare `API_KEY`. This is
  best-effort and blocks env-based credentials and channels only; it does **not** reach
  credentials the engine could read from files under `$HOME` (`~/.aws/credentials`,
  `~/.netrc`, `~/.config/gh/hosts.yml`), and it is not a network sandbox — which is why
  the code-only invocation above is what the safety posture actually rests on.
- **Confidence gate — honest scope: it applies to edges on current engine output.**
  `EXTRACTED` records emit; `INFERRED` records are quarantined to
  `Generated/graphify/NEEDS_VERIFICATION.jsonl` (never the index); `AMBIGUOUS` is dropped
  and counted. A dependency edge inherits the WEAKEST confidence among itself and both
  endpoint nodes — an edge touching a quarantined node is quarantined, one touching a
  dropped node is dropped. Measured fact (`graphifyy==0.9.43`, every repo tested): **node
  records carry no `confidence` field at all**, so they default to `EXTRACTED` — for nodes
  the gate is a forward-compatible hook today, not a filter. The diagnostic is scoped to
  that fact: a **100%-absent** count is reported as the expected baseline, and a `WARNING`
  is reserved for a **partial** split, which is the only shape that actually signals schema
  drift. (Warning on any non-zero count meant warning on every clean run, at a count equal
  to the whole node set — the reading this paragraph explicitly retracts.) Only nodes are
  counted; edges carry no `confidence` key by design, which is why `weakest_confidence`
  exists. Unknown node kinds are counted on stderr, never emitted.
- **Vendored/generated/minified code is excluded before emission** (`node_modules/`,
  `vendor/`, `dist/`, `build/`, `target/`, `*.min.js`, `*-bundle.js`, `swagger-ui/`,
  virtualenvs, ...), counted and reported as `vendor_excluded`. Rationale: minified bundles
  have no meaningful lines to cite, and on one real service 827 of 3,969 records (20.8%)
  described Swagger's internals rather than the service.
- **Fail-closed on citations:** a node or edge whose line number cannot be resolved is
  dropped and counted, never emitted with a fabricated `line: 1`. A symbol record must
  cite the line that DECLARES the symbol, and for Python that is settled by `ast`, not by
  searching for the name: a word-boundary search finds `campaign` on a neighbouring
  function's docstring but not inside `load_campaign_template`, which put 1,341 of 2,069
  handler rows on a line other than the declaration and published 16 `path:line` locations
  as the definition of two symbols each — every one stamped `VERIFIED`, because the T3 gate
  only asks for token overlap on the cited line. A declaration `ast` cannot confirm —
  unparseable file, no such name, or a tie between same-named declarations — goes to
  `NEEDS_VERIFICATION.jsonl`. The bounded forward token scan remains the rule for languages
  the adapter cannot parse, where the engine cites an annotation rather than the
  declaration (1,751 of 1,774 gate failures on a real JAX-RS service).
  A node that is not a symbol at all is dropped and counted as `file_nodes_not_symbols`:
  the engine emits one node per source file whose label IS the filename, plus — for every
  shell script — a second per-file node labelled `"<basename> script"` (a
  `bash_entrypoint`), and no line of a file declares the file. Its `identifier` cell only
  restates the tail of its `path` cell, so the gate — which scores Field+Value against the
  cited line and deliberately excludes the path — rejects it even at the file's own line 1
  (of 592 such nodes on one Python service — 586 file nodes plus 6 `bash_entrypoint`
  duplicates from its own `scripts/*.sh` — line 1 verifies 60 by coincidence, fails 461
  and does not exist for 71; 2 of 431 on the JAX-RS one, which has no per-file
  shell-script duplicate), while sending it through the token scan instead lands on the
  line that declares something ELSE. Between them the two rules take duplicated `path:line`
  locations — one location published as the definition of two symbols, each stamped
  `VERIFIED` — from 22 to 0 on the Python service and from 164 to 3 on the JAX-RS one,
  where the residue is the token scan's own and not this class: two enum constants that
  snap to the same line, and two test methods whose names differ only by a `_`.
- **Stale-output safety:** **every** artifact the adapter derives is removed before the
  engine runs — the engine-native `graphify-out/` tree AND `CODE_GRAPH.jsonl`,
  `NEEDS_VERIFICATION.jsonl` and `CODE_INDEX_RECORDS.jsonl` — and a non-zero engine exit
  emits nothing. Clearing only the engine's own output was one layer short: the derived
  files are written conditionally, so a failed run, or one that honestly produced zero
  edges or zero `INFERRED` records, left the previous run's file on disk stamped with the
  previous run's `engine=` and nothing downstream could tell. That matters most for
  `NEEDS_VERIFICATION.jsonl`, which is the list an operator is told to check before
  promoting anything.
- **Provenance survives the Phase 1.5 boundary.** The materialiser keeps only the four
  contract fields, marks every row `VERIFIED`, then deletes the extractor file — so nothing
  downstream would record which `CODE_INDEX.md` rows came from a third-party engine rather
  than the first-party extractors. The adapter mirrors exactly what it sent to stdout,
  `engine`/`confidence` included, to `Generated/graphify/CODE_INDEX_RECORDS.jsonl`.
- **Engine output** stays in `$REPO_PATH/Generated/graphify/`. That path is **not** covered
  by any existing ignore rule, so the adapter writes `Generated/graphify/.gitignore`
  (containing `*`) on every run to keep the engine's output out of the target repo's
  history.
- **Dependency edges never reach stdout.** At real-repo scale they are the bulk of the
  output (1,803 of 3,159 records on the largest test repo) and would blow the eager-load
  activation budget of the `CODE_INDEX.md` they feed. `EXTRACTED` dependency records are
  written to `Generated/graphify/CODE_GRAPH.jsonl` for on-demand use instead.
- Env knobs: `GRAPHIFY_PYTHON` (interpreter that runs the engine — see Preflight above).
  `GRAPHIFY_CMD` (default: `<engine interpreter> -m graphify`). A non-default
  `GRAPHIFY_CMD` is a code-execution surface, so it is honoured **only when
  `GRAPHIFY_ALLOW_CMD_OVERRIDE=1` is also set** and is logged loudly; without the gate the
  override is ignored. Note the asymmetry with `GRAPHIFY_PYTHON`, which needs no gate
  because it names an interpreter while the module stays hard-coded to `-m graphify`. When
  a command override is honoured, the packaged version floor is skipped and provenance is
  stamped from `GRAPHIFY_ENGINE_ID` (default `graphifyy==unknown`).
  `GRAPHIFY_SKIP_PREFLIGHT=1` bypasses the installed-package lookup (test seam, logged).
  `GRAPHIFY_SUBCOMMAND` (default `update`) and `GRAPHIFY_ARGS` (default `--no-cluster`)
  require `GRAPHIFY_ALLOW_LLM_PATH=1` — a deliberately separate gate from the command one,
  since every stub-engine test needs the command gate and sharing one variable would hand
  the larger power to every test seam. `GRAPHIFY_TIMEOUT` (default 900s; the Phase 1.5 hook
  caps it at 300s, because default-on puts the engine on the critical path of every
  conversion). A malformed value on any of these is reported and skipped cleanly rather
  than raising, and so is an unwritable target repo — the adapter always exits 0.

**Requires:** `python3 3.9+` to run the adapter; `graphifyy >= 0.9.24` installed in a
Python **3.10+** interpreter for the engine to actually run (point `GRAPHIFY_PYTHON` at it
if that is not the interpreter running the adapter). Engine absent → clean skip.

---

### `extract_git_ownership.sh` (ownership extractor — different schema, T1 v2)

```bash
bash scripts/onboarding/extract_git_ownership.sh <REPO_PATH> [--months N]
```

Emits one JSON record per top-level directory area using the **T1 ownership schema v2**:

```json
{
  "area": "src/auth",
  "original_architect": "Alice <a@example.com>",
  "current_maintainer": "Bob <b@example.com>",
  "codeowners_entry": "@team-auth",
  "catalog_info_owner": "team-platform",
  "agreement": "AGREE",
  "derivation_date": "2026-08-02",
  "top_committers": ["Alice <a@example.com>", "Bob <b@example.com>"],
  "last_touched_date": "2025-11-04",
  "commit_count": 42
}
```

Default look-back window: 12 months.

**Bot filtering:** reads `scripts/onboarding/bot_identities.txt`. Bots are excluded from all
committer fields and `commit_count`. Areas where ALL commits are bots are silently dropped.

**Email deduplication (B17):** The identity counter is keyed on the **lowercased email
address**, not on `"Name <email>"`. This means two display names for the same email address
(e.g. `relhousieny 14 commits` + `Rany ElHousieny 5 commits`, same email) are counted as one
person (true total: 19). The canonical display name for the output record is the most-frequent
name seen for that email address.

**Agreement semantics:**

- `AGREE` — git-derived owner and at least one static source (CODEOWNERS/catalog-info) match.
- `CONFLICTING` — at least one static source present but disagrees with git history.
- `SINGLE_SOURCE` — only git history available (no CODEOWNERS, no catalog-info spec.owner).

**Requires:** `git`, `bash 3.2+`, `awk`, `sort`, `python3 3.9+` (for JSON-safe serialization)

---

### `readiness_report.py` (scored agent-readiness report — local artifact only)

```bash
python3 scripts/onboarding/readiness_report.py <REPO_PATH> [--stdout]
```

Run by the onboarding agent at **Step 15.5** (after the Step 15 verification gate), and
usable standalone against any directory. Emits `Generated/READINESS_REPORT.md`: five gated
levels (L1 Orientation, L2 Hygiene, L3 Instruction layer, L4 Knowledge layer, L5 Governed
autonomy). Every criterion is a checkable filesystem fact with a remediation hint mapping
to a framework motion — the converter IS the remediation for L3-L5.

- **Mechanics lineage, honestly stated:** the gated-level scoring, difficulty axis
  (Basic/Intermediate/Advanced) and report-then-fix loop are adapted from Factory's
  Agent Readiness Model (docs.factory.ai/agent-readiness/overview, assessed 2026-08-14).
  Deliberately NOT adopted: platform persistence (this report never leaves the machine),
  the git `origin` requirement (a bare directory scores), and criteria without visible
  evidence commands.
- **The gate is 80%, and that rounds up to 100% here.** A level passes at >= 80% of its
  applicable criteria, and the achieved level is the highest level whose lower levels all
  pass too — a passing level above a failing one does not raise the score, and the report
  says so per row. With only 3-4 criteria per level, 80% rounds up to *every* applicable
  criterion (2/3 = 67%, 3/4 = 75%), so the report prints the derived threshold in a
  `Needed` column instead of implying tolerance that does not exist.
- **Local artifact, enforced rather than asserted:** the report records the absolute repo
  path, and the conversion's final instruction is `git add -A && git commit` (Step 16),
  so the writer drops a scoped `Generated/.gitignore` entry for `READINESS_REPORT.md`
  next to it. Same reasoning as this framework's own `.gitignore` rule for
  `Generated/Repos/*_PROFILE.md` ("carry machine paths... local-only").
- **N/A semantics:** a criterion may be not-applicable (excluded from the denominator, and
  printed with no remediation because it is not work owed). The `code-graph` criterion is
  pass-or-N/A: `Generated/graphify/CODE_GRAPH.jsonl` present means pass, absent means N/A.
  It is never a failure — an optional engine that is merely installed, or that ran and
  found no dependency edges, must not be able to lower a repo's level.
- **Eager-load budget is measured, not assumed:** sums the byte size of the whole
  Session-Init boundary the converter injects into `CLAUDE.md`
  (`CLAUDE.md`, `AGENTS.md`, `START_HERE*`, `Knowledge/KNOWLEDGE_GRAPH.md`,
  `Knowledge/CODE_INDEX.md`, `Knowledge/Source of Truth/PROJECT_VISION.md`,
  `Generated/PROGRESS_TRACKER.md`, `.claude/skills/*/SKILL.md`) against the framework's
  own documented limit — 360,000 bytes, the same set and unit as the `wc -c` measurement
  in `REPO_ONBOARDING_AGENT.md` "Activation Token Budget" (ref: PROJ-2486/2487).
- **L5 measures use, not scaffolding:** the converter creates `Generated/session_logs/`
  and `Knowledge/Source of Truth/` itself, so those criteria require at least one real
  file, not just the directory.
- Always exits 0 — including on a read-only target tree (the write failure becomes a
  stderr warning). One-line JSON summary on stderr for pipelines.

**Requires:** `python3 3.9+`

---

### `bot_identities.txt`

```
scripts/onboarding/bot_identities.txt
```

Deny-list of bot/CI identities for `extract_git_ownership.sh`. One pattern per line.
Comments start with `#`. Two matching modes:

- **EMAIL_GLOB** — lines containing `@` match against the email portion of `"Name <email>"` strings. Shell-style globs (`*`). Example: `*-sa@*`, `*@noreply.*`
- **NAME_SUBSTR** — lines NOT containing `@` are matched case-insensitively as a substring of the full `"Name <email>"` string. Example: `renovate`, `dependabot`

Edit this file to add org-specific bot identities. Default entries cover `the-pipeline-service-account`,
`renovate[bot]`, `dependabot[bot]`, `gitlab-ci-token`, noreply patterns, and `*-sa@*` service accounts.

---

### `verify_citations.sh` (T3 hard gate)

```bash
bash scripts/onboarding/verify_citations.sh <ARTIFACT_FILE> [REPO_PATH] [OPTIONS]
```

`REPO_PATH` is optional.  If omitted — or if the next argument starts with `--` — CWD
is used as the repo root.  All three invocation forms work:

```bash
bash verify_citations.sh artifact.md --dry-run             # REPO_PATH defaults to CWD
bash verify_citations.sh artifact.md /path/to/repo         # positional REPO_PATH
bash verify_citations.sh artifact.md --repo-path /repo     # named --repo-path flag
```

**Claim derivation (B2):**

- For table rows (`| Field | Value | Evidence | Status |`): claim = Field + Value cells only
  (never from the full row, which would include the citation path and create self-referential overlap).
- For standalone `**SOURCE:** path:line` lines: claim = nearest preceding non-citation line.

**NOT_FOUND exemption (B4):** A row is exempt **only** when the **Status column** (last
`|cell|`) exactly equals `NOT_FOUND` (case-insensitive). The word appearing anywhere else in
the row is NOT sufficient — row must have `... | NOT_FOUND |` at the end.

**Empty-artifact guard (B5):** `CODE_INDEX.md`, `VALIDATION_SUMMARY.md`, and
`PHASE1_DETECTION.md` must contain at least 1 citation — exit 1 otherwise. Override with
`--min-citations 0`.

**Threshold validation (B6):** `--threshold 0` and `--threshold > 1` are rejected.
Cited-line span is capped at 40 lines to prevent dilution via large ranges (e.g. `file:1-9999`).

**SHA pinning (B3):** `--sha S` resolves cited files via `git -C REPO_PATH show S:PATH`
rather than reading the mutable working tree. Use the HEAD SHA from `PHASE1_DETECTION.md`
for reproducible gates. Default (no `--sha`) reads the working tree.

**Path-token guards** prevent false-positives on version strings in prose
(e.g. `Phase 1.5.2:100` or `v2.0:5`):

- Bare integers (`12:34`) are skipped.
- Version-like tokens matching `/^v?\d+\.\d+(\.\d+)*$/` are skipped.
- Tokens with neither `/` nor a known file extension are skipped.

Options:

- `--threshold N` — minimum overlap score in **(0, 1]** (default: 0.10). 0 and >1 rejected.
- `--dry-run` — print results to stdout; do NOT write `VALIDATION_SUMMARY.md`
- `--summary-path P` — path for `VALIDATION_SUMMARY.md` (default: alongside artifact)
- `--repo-path P` — root of the repo being verified (default: CWD)
- `--sha S` — resolve cited files at pinned commit SHA (default: working tree)
- `--min-citations N` — minimum expected citations (default: 1 for citation-bearing names)

**Exit codes:**

- `0` — all citations resolved; citation count ≥ minimum
- `1` — citation failure, missing file, or zero citations in citation-bearing artifact

**Also checks for forbidden phrases (T5):** `probably`, `likely`, `typically`, `generally`.

**Emits `VALIDATION_SUMMARY.md` (T6):** total claims / resolved / percentage.

**Regression fixture:** `scripts/onboarding/tests/fixtures/non_resolving_citations.md` +
`scripts/onboarding/tests/fixtures/sample_source.md`. Running the resolver against
`non_resolving_citations.md` MUST exit non-zero — CI enforces this.

---

### `merge_sme_contacts.py`

```bash
python3 scripts/onboarding/merge_sme_contacts.py \
    --repo-path <REPO_PATH> \
    [--months 12] \
    [--output <path>] \
    [--dry-run]
```

Invokes `extract_git_ownership.sh` internally, then merges the auto-generated ownership
table into `Knowledge/SME_CONTACTS.md` using structural markers:

```
<!-- BEGIN AUTO -->
... machine-generated rows ...
<!-- END AUTO -->
```

Human-authored rows **outside** these markers are preserved verbatim on every re-run.

`--dry-run` prints the proposed merged content to stdout without writing to disk.

**Requires:** `python3 3.9+`, `bash 3.2+` (for the subsidiary shell script)

---

### `ensure_graphify.sh` (Phase 1.5 engine bootstrap — resolve or install)

```bash
bash scripts/onboarding/ensure_graphify.sh      # engine python path on STDOUT
```

The dependency graph is what separates a rich agent (symbol-level CODE_INDEX,
`CODE_GRAPH.jsonl` impact analysis, quarantined-uncertainty sidecar) from a surface-level
one, so Phase 1.5 treats the engine as expected-present rather than optional: this script
tries every reasonable path to an engine before conceding, and a skip is legitimate ONLY
when installation is provably impossible on this machine.

Resolution ladder, first success wins:

1. `GRAPHIFY_PYTHON` override — the operator names the interpreter exactly
2. An existing engine venv — reused; a **broken** venv is rebuilt, not trusted
3. Bootstrap — the newest compatible `python3.x` on PATH creates the venv and pip-installs
   the pinned engine

**Exit codes (Phase 1.5 keys its behaviour off these — keep them stable):**

| rc | Meaning |
|---|---|
| 0 | Engine ready; the venv's python path is on STDOUT and nothing else ever is |
| 2 | Disabled by the operator (`GRAPHIFY_ADAPTER=0/false/no/off`) — respected, quiet. Unreachable from Phase 1.5's affirmative arm, which normalises the flag identically |
| 3 | Provably impossible on this machine; the reason is on STDERR (no python >= 3.10, venv creation failed, pip install failed e.g. offline, corrupt install) |

The engine dist name and module name DIFFER: pip installs `graphifyy` (the pin), python
imports `graphify`. Both are probed so a future rename keeps working.

**Env:** `GRAPHIFY_PIN` (default `graphifyy==0.9.43`), `GRAPHIFY_VENV_DIR` (default
`$HOME/.venvs/graphify`), `GRAPHIFY_PYTHON`, `GRAPHIFY_ADAPTER`.

**Requires:** `bash 3.2+` (no `${VAR,,}`), and a `python3 >= 3.10` on PATH to bootstrap

---

### `golden_facts.py` (Step 15.7 standing drift gate)

```bash
python3 scripts/onboarding/golden_facts.py derive <REPO_PATH> [--rederive]
python3 scripts/onboarding/golden_facts.py assert <REPO_PATH>
```

Derives named, mechanically checkable claims from evidence the conversion just
gate-verified (CODE_INDEX rows, the Phase 1 framework detection, one dependency edge) and
writes them to `Knowledge/golden/GOLDEN_FACTS.{jsonl,md}`. `assert` re-verifies every fact
against the current tree and rewrites the md status column.

`derive` is DERIVE-ONCE: an existing `GOLDEN_FACTS.jsonl` is left untouched, because
overwriting the anchors on every run would defeat the drift detection they exist for.
`--rederive` is the explicit refresh. Selection is deterministic (sorted, capped), so two
derives from the same tree produce identical files, and the token matching mirrors
`verify_citations.sh`'s tokenizer so the two gates cannot disagree about the same claim.

First-run assertion is trivially green by construction. The value is UPDATE-mode re-runs,
where a moved endpoint or a reworked auth pattern becomes a HARD FAILURE instead of a
silent lie.

**Exit codes:** `assert` 0 all pass / 1 any fail / 3 usage. `derive` **3 means "nothing
derivable"** — a docs repo or a pure library has no endpoint / entry_point / config rows,
which is a complete conversion, not a failed one. Step 15.7 records
`Knowledge/golden/GOLDEN_FACTS_NONE.md` and reports it as an L5 readiness gap;
`final_verify.py`'s either-contract accepts that file in place of the facts.

**Requires:** `python3 3.9+`

---

### `propose_codeowners.py` (Step 10.9 — a draft, never authority)

```bash
python3 scripts/onboarding/propose_codeowners.py <REPO_PATH>
```

Writes `CODEOWNERS.proposed` at the repo root: top recent committers overall, plus
per-directory rules only where a first-level directory's ownership evidence actually
differs from the root rule. It is a PROPOSAL by construction — CODEOWNERS drives GitLab
approval rules, so a converter that commits one is granting review authority nobody
consented to. The owning team reviews, renames to `CODEOWNERS`, and commits; that rename
is what flips the L2 readiness criterion.

Evidence rules: a recent window (default 400 commits) rather than full history, because
review authority should reflect who works here now; the same bot filter as the SME
derivation (builtin list + `.agentic/bots.txt`); and owners are **emails**, verbatim from
git identities — valid GitLab CODEOWNERS syntax, and honest, since mapping emails to
`@usernames` would be guessing.

UPDATE-safe: a real `CODEOWNERS` in any of the four conventional locations means the repo
is already governed — exit 0, write nothing, say so. An existing `.proposed` is
regenerated, since it is a derived draft and the reviewed copy is the one the team renamed.

**Exit codes:** 0 written or already-governed; 3 unusable (not a git repo, or no non-bot
history), reason on stderr.

**Requires:** `python3 3.9+`, `git`

---

### `final_verify.py` (Step 15.8 — the everything-created hard gate)

```bash
python3 scripts/onboarding/final_verify.py <REPO_PATH>
```

The LAST gate before a conversion presents results, and equally useful standalone as a
health check on an already-converted repo. The Step 5 `ls` proves files exist and the
completion checklist is prose an agent can skim past; this is one command, one exit code,
and a table naming exactly what is missing.

Five check classes, each derived from the conversion's own contract:

| Class | What it proves |
|---|---|
| `required` | Every required artifact exists AND is non-empty — an empty `CLAUDE.md` is a created file and a failed conversion at the same time |
| `glob` | The domain-agent skill, `-ai` command and agent source prompt globs each match at least one non-empty file |
| `either` | Contract alternatives: `CODEOWNERS` \| `CODEOWNERS.proposed`; `CODE_GRAPH.jsonl` \| one of the three markers that say why there is no graph (`GRAPHIFY_BOOTSTRAP.err`, `GRAPHIFY_SKIPPED`, `GRAPHIFY_NO_EDGES`); golden facts \| `GOLDEN_FACTS_NONE.md` |
| `registered` | `Knowledge/CODE_INDEX.md` is named in `CLAUDE.md` (Session-Init), `KNOWLEDGE_GRAPH.md` and `DOCUMENT_INDEX.md` — a generated index nobody can navigate to is dead weight |
| `no-leak` | No unexpanded `$REPO_NAME_LOWER` / `${REPO_NAME_UPPER}` / `$TODAY` placeholders in emitted markdown |

The N-way `either` form is deliberate. "No dependency graph" and "no golden facts" are
legitimate outcomes for real repo classes — the kill switch is documented, a docs repo has
no endpoints — and a two-way form turned both into a hard conversion failure with no way
through. Absence still has to be STATED, which is why the alternatives are marker files
and not a loosened check.

**Exit codes:** 0 all pass / 1 any fail (failures repeated on stderr) / 3 usage.

**Requires:** `python3 3.9+`

---

## Rule 11 compliance

All `.env`-value parsing in these scripts uses `cut -d'=' -f1` (key extraction only) or
`cut -d'=' -f2-` (value extraction with trailing dash) to avoid the documented
TOKEN TRUNCATION BUG with embedded `=` characters in secrets.

---

## Testing

Integration tests live in `scripts/onboarding/tests/`.
Run with:

```bash
pip install pytest   # if not already installed
python3 -m pytest scripts/onboarding/tests/ -v
```

Each test builds a minimal in-memory fixture repo using `tmp_path` and validates:

- Extractor output parses as valid JSON-lines.
- Every record has a non-empty `path`, `line > 0`, non-empty `kind` and `identifier`.
- Expected `kind` values appear for the given fixture.
- Stderr is empty on happy-path runs (warnings should not appear for clean inputs).
- Edge cases: empty repos, `SyntaxError`-triggering Python, malformed input, `.env` files,
  Pydantic `BaseSettings`, `application.properties`, merge failure paths.
