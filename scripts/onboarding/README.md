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
floor verbatim. Python 3.9 is the declared minimum because:

- It is the oldest interpreter known to be in active use on operator machines (verified:
  `/usr/bin/python3 -V` → `Python 3.9.6` on the minimum-interpreter target).
- `dict |` merge (PEP 584) and `str.removeprefix`/`removesuffix` (PEP 616) require 3.9 —
  both are safe to use at or above the floor.
- PEP 604 union-type annotations (`X | Y`) require **Python 3.10+** and are therefore
  **forbidden** in this directory. Use `typing.Optional[X]` instead (PEP 484).
- Python 3.8 is not a supported target; no operator machine is known to run it.

Bash 3.2 compatibility is already enforced — the `# Requires: bash 3.2+` note on
each script documents and locks that guarantee.

**Sweep results:** `git grep -nE '\| *None|None *\|' scripts/onboarding/`
returned exactly one hit prior to this fix (`verify_citations.sh:311`), now resolved.
`git grep -nE '^\s*match .*:$' scripts/onboarding/*.py scripts/onboarding/*.sh` — 0 hits.
`git grep -nE 'declare -A|mapfile|readarray|\$\{[a-zA-Z_]+,,\}' scripts/onboarding/` — 0 hits
(two results in `extract_express.sh` comments documenting what NOT to use — not live code).

---

## Contract Overview

This directory contains **two distinct families** of scripts with **different stdout schemas**.
Do not mix them up.

| Family                                                                 | Scripts                                                                                      | Schema                                                                                    |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Code-symbol extractors                                                 | `extract_spring_boot.sh`, `extract_fastapi.py`, `extract_express.sh`, `extract_terraform.sh` | `{path, line, kind, identifier}` — one record per symbol                                  |
| Optional engine adapter (ON by default when engine installed, opt-out) | `extract_graphify.py`                                                                        | Same `{path, line, kind, identifier}` contract + additive `{engine, confidence}` fields   |
| Ownership extractor                                                    | `extract_git_ownership.sh`                                                                   | `{area, top_committers, last_touched_date, commit_count}` — one record per top-level area |

---

## Code-Symbol Extractor CLI Contract

The four code-symbol extractors write **JSON-lines** to stdout.
Each line is one record:

```json
{"path":"<relative-path>","line":<int>,"kind":"<kind>","identifier":"<identifier>"}
```

| Field        | Type    | Description                        |
| ------------ | ------- | ---------------------------------- |
| `path`       | string  | File path relative to `$REPO_PATH` |
| `line`       | integer | 1-based line number of the symbol  |
| `kind`       | string  | One of the values below            |
| `identifier` | string  | Human-readable name / label        |

### `kind` values (code-symbol extractors only)

| Kind            | Meaning                                                                      |
| --------------- | ---------------------------------------------------------------------------- |
| `module`        | Top-level package, Maven module, or directory boundary                       |
| `entry_point`   | Application entry point (main class, `FastAPI()`, etc.)                      |
| `endpoint`      | HTTP/RPC endpoint or CLI command                                             |
| `config`        | Config key or env-var (`@Value`, `process.env.KEY`, `var.name`)              |
| `integration`   | External dependency / integration point                                      |
| `test_location` | Test file or test directory root                                             |
| `handler`       | Function/method symbol (optional Graphify adapter only)                      |
| `dependency` | Import/call edge, identifier `"src -> dst"` (optional Graphify adapter only; written to `Generated/graphify/CODE_GRAPH.jsonl`, never stdout — keeps the eager-loaded index inside the activation token budget) |

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

`extract_git_ownership.sh` emits a **different** JSON-lines schema (v2):

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

| Field                | Type             | Description                                                                                                         |
| -------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------- |
| `area`               | string           | Top-level directory name (e.g. `"src"`, `"tests"`, `"."` for root)                                                  |
| `original_architect` | string or null   | All-time most-active committer in the area (bot-filtered)                                                           |
| `current_maintainer` | string or null   | Most recent committer in the window (bot-filtered)                                                                  |
| `codeowners_entry`   | string or null   | Matching CODEOWNERS entry for this area (null if no CODEOWNERS file)                                                |
| `catalog_info_owner` | string or null   | `spec.owner` from `catalog-info.yaml` (null if not present)                                                         |
| `agreement`          | string           | `AGREE` — git and static sources match; `CONFLICTING` — they disagree; `SINGLE_SOURCE` — only git history available |
| `derivation_date`    | string           | ISO-8601 date the record was derived                                                                                |
| `top_committers`     | array of strings | Up to 3 most-active human committers in the window, `"Name <email>"` format                                         |
| `last_touched_date`  | string           | ISO-8601 date of the most recent commit in the window                                                               |
| `commit_count`       | integer          | Total **human** (bot-filtered) commits in the window for this area                                                  |

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

**Source root detection:** If no `src/` directory exists, the extractor falls back to
scanning `$REPO_PATH` root with `node_modules/build/dist/target` excluded. Explicit
`SRC_ROOTS` can be passed as extra arguments (from `PHASE1_DETECTION.md Step 3.5`).

**Bash 3.2 compatibility:** Uses `tr` instead of `${var,,}`, `while-read` instead of
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

**Source root detection:** Falls back to scanning `$REPO_PATH` when no `src/` exists.
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
python3 scripts/onboarding/extract_graphify.py <REPO_PATH>          # runs if graphifyy is installed
GRAPHIFY_ADAPTER=0 python3 scripts/onboarding/extract_graphify.py <REPO_PATH>   # kill switch
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
- **Preflight:** requires `graphifyy >= 0.9.24` installed (`pip install 'graphifyy==0.9.43'`,
  note the double `y`); absent or too old → clean skip with a loud stderr note. The floor is
  a known-good schema baseline, not a pin — the mapper is verified against `0.9.43` and
  tolerates additive drift. When a `GRAPHIFY_CMD` override is honoured (see the env knobs
  below) the operator has named their own engine, so the distribution floor is skipped and
  provenance is stamped from `GRAPHIFY_ENGINE_ID` (default `graphifyy==unknown`).
- **Code-only invocation — this is the egress guarantee.** The adapter calls only the
  engine's `update` subcommand ("re-extract code files and update the graph (no LLM
  needed)" per the engine help) with `--no-cluster`. The LLM-dependent paths (`extract`,
  community labeling) are never invoked.
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
- **Confidence gate:** `EXTRACTED` records emit; `INFERRED` records are quarantined to
  `Generated/graphify/NEEDS_VERIFICATION.jsonl` (never the index); `AMBIGUOUS` is dropped
  and counted. A dependency edge inherits the WEAKEST confidence among itself and both
  endpoint nodes — an edge touching a quarantined node is quarantined, one touching a
  dropped node is dropped. Records arriving with no `confidence` field are treated as
  `EXTRACTED`, counted separately, and reported with a `WARNING` so engine schema drift
  is visible. Unknown node kinds are counted on stderr, never emitted.
- **Fail-closed on citations:** a node or edge whose line number cannot be resolved is
  dropped and counted, never emitted with a fabricated `line: 1`.
- **Stale-output safety:** the engine output directory is cleared before each run, and a
  non-zero engine exit emits nothing — a failed run can never republish the previous run's
  symbols.
- **Engine output** stays in `$REPO_PATH/Generated/graphify/`. That path is **not** covered
  by any existing ignore rule, so the adapter writes `Generated/graphify/.gitignore`
  (containing `*`) on every run to keep the engine's output out of the target repo's
  history.
- **Dependency edges never reach stdout.** At real-repo scale they are the bulk of the
  output (1,803 of 3,159 records on the largest test repo) and would blow the eager-load
  activation budget of the `CODE_INDEX.md` they feed. `EXTRACTED` dependency records are
  written to `Generated/graphify/CODE_GRAPH.jsonl` for on-demand use instead.
- Env knobs: `GRAPHIFY_CMD` (default: the adapter's own interpreter `-m graphify` — install
  graphifyy into the interpreter that runs the adapter). A non-default `GRAPHIFY_CMD` is a
  code-execution surface, so it is honoured **only when `GRAPHIFY_ALLOW_CMD_OVERRIDE=1` is
  also set** and is logged loudly; without the gate the override is ignored. When honoured,
  the packaged version floor is skipped and provenance is stamped from `GRAPHIFY_ENGINE_ID`
  (default `graphifyy==unknown`). `GRAPHIFY_SKIP_PREFLIGHT=1` bypasses the installed-package
  lookup (test seam, logged). Also: `GRAPHIFY_SUBCOMMAND` (default `update`), `GRAPHIFY_ARGS`
  (default `--no-cluster`), `GRAPHIFY_TIMEOUT` (default 900s). A malformed value on any of
  these is reported and skipped cleanly rather than raising.

**Requires:** `python3 3.9+`, `graphifyy >= 0.9.24` (only when the engine is present)

---

### `extract_git_ownership.sh` (ownership extractor — different schema, v2)

```bash
bash scripts/onboarding/extract_git_ownership.sh <REPO_PATH> [--months N]
```

Emits one JSON record per top-level directory area using the **ownership schema v2**:

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

**Email deduplication:** The identity counter is keyed on the **lowercased email
address**, not on `"Name <email>"`. This means two display names for the same email address
(e.g. `asmith 14 commits` + `Alice Smith 5 commits`, same email) are counted as one
person (true total: 19). The canonical display name for the output record is the most-frequent
name seen for that email address.

**Agreement semantics:**

- `AGREE` — git-derived owner and at least one static source (CODEOWNERS/catalog-info) match.
- `CONFLICTING` — at least one static source present but disagrees with git history.
- `SINGLE_SOURCE` — only git history available (no CODEOWNERS, no catalog-info spec.owner).

**Requires:** `git`, `bash 3.2+`, `awk`, `sort`, `python3 3.9+` (for JSON-safe serialization)

### `bot_identities.txt`

```
scripts/onboarding/bot_identities.txt
```

Deny-list of bot/CI identities for `extract_git_ownership.sh`. One pattern per line.
Comments start with `#`. Two matching modes:

- **EMAIL_GLOB** — lines containing `@` match against the email portion of `"Name <email>"` strings. Shell-style globs (`*`). Example: `*-sa@*`, `*@noreply.*`
- **NAME_SUBSTR** — lines NOT containing `@` are matched case-insensitively as a substring of the full `"Name <email>"` string. Example: `renovate`, `dependabot`

Edit this file to add org-specific bot identities. Default entries cover `renovate[bot]`,
`dependabot[bot]`, `github-actions[bot]`, `gitlab-ci-token`, noreply patterns, and `*-sa@*`
service-account globs.

---

### `verify_citations.sh` (citation hard gate)

```bash
bash scripts/onboarding/verify_citations.sh <ARTIFACT_FILE> [REPO_PATH] [OPTIONS]
```

`REPO_PATH` is optional. If omitted — or if the next argument starts with `--` — CWD
is used as the repo root. All three invocation forms work:

```bash
bash verify_citations.sh artifact.md --dry-run             # REPO_PATH defaults to CWD
bash verify_citations.sh artifact.md /path/to/repo         # positional REPO_PATH
bash verify_citations.sh artifact.md --repo-path /repo     # named --repo-path flag
```

**Claim derivation:**

- For table rows (`| Field | Value | Evidence | Status |`): claim = Field + Value cells only
  (never from the full row, which would include the citation path and create self-referential overlap).
- For standalone `**SOURCE:** path:line` lines: claim = nearest preceding non-citation line.

**NOT_FOUND exemption:** A row is exempt **only** when the **Status column** (last
`|cell|`) exactly equals `NOT_FOUND` (case-insensitive). The word appearing anywhere else in
the row is NOT sufficient — row must have `... | NOT_FOUND |` at the end.

**Empty-artifact guard:** `CODE_INDEX.md`, `VALIDATION_SUMMARY.md`, and
`PHASE1_DETECTION.md` must contain at least 1 citation — exit 1 otherwise. Override with
`--min-citations 0`.

**Threshold validation:** `--threshold 0` and `--threshold > 1` are rejected.
Cited-line span is capped at 40 lines to prevent dilution via large ranges (e.g. `file:1-9999`).

**SHA pinning:** `--sha S` resolves cited files via `git -C REPO_PATH show S:PATH`
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

**Also checks for forbidden phrases:** `probably`, `likely`, `typically`, `generally`.

**Emits `VALIDATION_SUMMARY.md`:** total claims / resolved / percentage.

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

## Env-var parsing convention

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
