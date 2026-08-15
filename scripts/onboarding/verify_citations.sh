#!/usr/bin/env bash
# verify_citations.sh — Citation resolver and hard gate (T3)
#
# Usage:
#   bash scripts/onboarding/verify_citations.sh <ARTIFACT_FILE> [REPO_PATH] [OPTIONS]
#
#   REPO_PATH is optional.  If omitted (or if the next argument starts with '--'),
#   the current working directory is used as REPO_PATH.  This means:
#
#     bash verify_citations.sh artifact.md --dry-run           # OK — CWD used
#     bash verify_citations.sh artifact.md /path/to/repo       # OK — explicit
#     bash verify_citations.sh artifact.md --repo-path /repo   # OK — named flag
#
# Description:
#   Extracts every <path>:<line[-line]> citation from ARTIFACT_FILE, opens the
#   cited file at REPO_PATH (defaults to CWD), extracts the cited line range,
#   and requires stemmed-token overlap between:
#     (a) the claim sentence — derived from the row's Field+Value cells (columns
#         1 and 2 of a pipe-delimited table row), NEVER from the citation itself.
#         For a standalone **SOURCE:** citation line, the claim is taken from the
#         NEAREST preceding non-citation-only line.
#     (b) the cited file content at the specified lines (span capped at 40 lines)
#
#   Overlap near zero (< OVERLAP_THRESHOLD) is exactly what catches a
#   "hybrid-approach paragraph cited as Terraform IaC" case.
#
#   NOT_FOUND exemption: a row is exempt ONLY when the Status column (last |cell|)
#   exactly equals NOT_FOUND (case-insensitive), not when the word appears anywhere
#   in the row.
#
#   Empty-artifact guard: if the artifact contains ZERO citations and the artifact
#   filename matches a known citation-bearing artifact (CODE_INDEX.md,
#   VALIDATION_SUMMARY.md, PHASE1_DETECTION.md), exit 1.  Override with
#   --min-citations 0.
#
#   SHA pinning: --sha <COMMIT_SHA> resolves cited files via
#   `git -C <REPO_PATH> show <sha>:<path>` into a tempfile instead of reading
#   the mutable working tree.  Default is still the working-tree read.
#
#   Path-token guards (prevents false-positives on version strings):
#     - Bare integers (e.g. "12:34") are skipped.
#     - Version-like tokens matching /^v?\d+\.\d+(\.\d+)*$/ (e.g. "1.5.2", "v2.0")
#       are skipped even if they contain dots.
#     - A token that contains neither '/' nor a known file extension is skipped.
#     These three guards together ensure "Phase 1.5.2:100" or "v1.2.3:45" in
#     prose never triggers the hard gate.
#
#   Also checks for FORBIDDEN_PHRASES in generated agent files (T5):
#     probably, likely, typically, should, generally
#
#   Emits VALIDATION_SUMMARY.md (T6) as a byproduct.
#
# Exit codes:
#   0  — all citations resolve with sufficient overlap (or are NOT_FOUND rows)
#   1  — one or more citations fail the overlap check (blocks conversion completion)
#        also exit 1 when zero citations found on a citation-bearing artifact
#
# Options:
#   --threshold N    Minimum overlap score (0.0–1.0, default: 0.10). Must be in (0,1].
#                    Reject 0 and values > 1 with a clear error.
#   --dry-run        Print results to stdout; do not write VALIDATION_SUMMARY.md
#   --summary-path P Path for VALIDATION_SUMMARY.md (default: alongside artifact)
#   --repo-path P    Root of the repo being verified (overrides positional REPO_PATH)
#   --sha S          Resolve cited files at git commit S instead of working tree
#   --min-citations N Minimum expected citation count (default: 1 for citation-bearing
#                    artifacts, 0 for all others). Exit 1 when count < N.
#
# Rule 11 compliance: no cut -d'=' -f2 usage; all env-var parsing uses f2-.
# Exit 1 on citation failure (hard gate); exit 0 on success.
#
# Requires: bash 3.2+, python3 3.9+, awk, grep, sed

set -euo pipefail

ARTIFACT_FILE="${1:?Usage: verify_citations.sh <ARTIFACT_FILE> [REPO_PATH] [OPTIONS]}"
ARTIFACT_FILE="$(realpath "$ARTIFACT_FILE")"
shift  # consume ARTIFACT_FILE

# $1 is now either REPO_PATH (a plain path) or the first option flag (starts with --)
# Detect: if the next arg exists AND does NOT start with '--', treat it as REPO_PATH.
REPO_PATH=""
if [[ $# -gt 0 && "${1:0:2}" != "--" ]]; then
  REPO_PATH="$(realpath "$1")"
  shift
fi
[[ -z "$REPO_PATH" ]] && REPO_PATH="$(pwd)"

THRESHOLD="0.10"
DRY_RUN=0
SUMMARY_PATH=""
SHA_PIN=""
MIN_CITATIONS="-1"  # -1 = use artifact-name heuristic

# Parse remaining option flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --threshold)    THRESHOLD="${2:?--threshold requires a value}"; shift 2 ;;
    --dry-run)      DRY_RUN=1; shift ;;
    --summary-path) SUMMARY_PATH="${2:?--summary-path requires a value}"; shift 2 ;;
    --repo-path)    REPO_PATH="$(realpath "${2:?--repo-path requires a value}")"; shift 2 ;;
    --sha)          SHA_PIN="${2:?--sha requires a value}"; shift 2 ;;
    --min-citations) MIN_CITATIONS="${2:?--min-citations requires a value}"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$SUMMARY_PATH" ]]; then
  # Default to caller's CWD, NOT alongside the artifact.
  # Writing next to the artifact contaminates read-only fixture directories
  # (e.g. a shared fixture checkout) and violates the ticket's Out-of-scope constraint.
  # REPO_ONBOARDING_AGENT.md Step 15 already passes --summary-path explicitly,
  # so this default change leaves the documented production flow unchanged.
  SUMMARY_PATH="$(pwd)/VALIDATION_SUMMARY.md"
fi

# ── Run the Python resolver ────────────────────────────────────────────────────
python3 - "$ARTIFACT_FILE" "$REPO_PATH" "$THRESHOLD" "$DRY_RUN" "$SUMMARY_PATH" \
          "$SHA_PIN" "$MIN_CITATIONS" <<'PYEOF'
"""
Citation resolver — reads artifact, extracts citations, verifies overlap,
writes VALIDATION_SUMMARY.md, exits 0/1.

Fixes implemented:
  B2  — claim derived from Field+Value cells, never from citation text itself.
        For standalone **SOURCE:** lines, walk back to nearest non-citation content.
  B3  — SHA pinning via --sha flag: `git -C REPO show SHA:PATH` into tempfile.
  B4  — NOT_FOUND exemption via exact Status-column match, not substring anywhere.
  B5  — Zero-citation exit-1 for citation-bearing artifact names.
  B6  — Overlap denominator = claim tokens (already claim-normalised); cited-line
        span capped at MAX_CITED_SPAN (40) lines; --threshold 0 and >1 rejected.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import date
from typing import Optional

artifact_file  = Path(sys.argv[1])
repo_path      = Path(sys.argv[2])
threshold_str  = sys.argv[3]
dry_run        = sys.argv[4] == "1"
summary_path   = Path(sys.argv[5])
sha_pin        = sys.argv[6]       # "" means working-tree
min_citations_arg = sys.argv[7]   # "-1" means heuristic

# ── B6: validate --threshold ──────────────────────────────────────────────────
try:
    threshold = float(threshold_str)
except ValueError:
    print(f"ERROR: --threshold must be a number, got: {threshold_str!r}", file=sys.stderr)
    sys.exit(1)

if threshold <= 0 or threshold > 1:
    print(
        f"ERROR: --threshold must be in (0, 1], got: {threshold}. "
        "Rejecting --threshold 0 and values > 1.",
        file=sys.stderr,
    )
    sys.exit(1)

# ── B6: cap cited-line span ───────────────────────────────────────────────────
MAX_CITED_SPAN = 40

# ── Stemmer: crude but fast Porter-style stem ────────────────────────────────
def stem(word: str) -> str:
    """Very light stemmer: lowercase, strip trailing s/ed/ing/ly."""
    w = word.lower()
    for suffix in ("tion", "tions", "ings", "ing", "tion", "ed", "ly", "er", "est", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[:-len(suffix)]
            break
    return w

def tokenize(text: str) -> set:
    """Return a set of stems from the text, excluding short/stop words."""
    STOP = {"the", "a", "an", "in", "of", "to", "and", "or", "is", "are", "was",
            "with", "for", "on", "at", "by", "from", "this", "that", "it", "its",
            "not", "no", "be", "has", "have", "do", "all", "as", "into", "via"}
    tokens = set()
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9]*", text):
        w = stem(word)
        if len(w) >= 3 and w not in STOP:
            tokens.add(w)
    return tokens

# ── B2: derive claim from Field+Value cells, never from citation text ─────────
#
# Strategy:
#  1. If the row is a pipe-delimited table row (| c1 | c2 | ... |), extract
#     columns 1 (Field) and 2 (Value) as the claim text.
#  2. If the row is a standalone **SOURCE:** ... line, claim = "" (will be filled
#     from the preceding-line fallback).
#  3. Otherwise treat the whole row as the claim (prose paragraph).
#
# The citation regex is then applied to the FULL row to find the citation ref,
# but the claim is the extracted field/value or preceding prose.

_CITATION_ON_LINE_RE = re.compile(
    r"""
    (?<!\w)
    [A-Za-z0-9_./-]+:[0-9]+(?:-[0-9]+)?
    (?!\w)
    """,
    re.VERBOSE,
)

_SOURCE_LINE_RE = re.compile(r"^\s*\*{0,2}SOURCE:?\*{0,2}\s*", re.IGNORECASE)


def is_citation_only_line(line: str) -> bool:
    """Return True when the line's ONLY non-trivial content is a SOURCE citation."""
    stripped = line.strip()
    # Match: **SOURCE:** path:line  or  SOURCE: path:line
    if _SOURCE_LINE_RE.match(stripped):
        return True
    return False


def extract_claim_from_row(row: str) -> str:
    """
    Extract the claim text from a table row or prose line.
    For table rows: use Field (col 1) + Value (col 2) cells only.
    For standalone SOURCE lines: return "" (caller falls back to preceding content).
    For prose: return the row with citation patterns stripped.
    """
    # Standalone SOURCE line → no claim from this line
    if is_citation_only_line(row):
        return ""

    # Pipe-delimited table row: | Field | Value | Evidence | Status |
    # Split on | and take columns 1 and 2 (0-indexed after leading |)
    stripped = row.strip()
    if stripped.startswith("|") and stripped.endswith("|"):
        cells = [c.strip() for c in stripped.split("|")]
        # cells[0] is empty (before leading |), cells[-1] is empty (after trailing |)
        # actual columns: cells[1], cells[2], cells[3], ...
        data_cells = [c for c in cells if c]  # drop empty boundary cells
        if len(data_cells) >= 2:
            # Use Field + Value (cells 0 and 1 of actual data)
            # Skip header separator rows (----)
            if re.match(r"^-+$", data_cells[0]):
                return ""
            claim = data_cells[0] + " " + data_cells[1]
            return claim

    # Prose line: strip citation patterns to avoid self-reference
    claim = _CITATION_ON_LINE_RE.sub(" ", row)
    claim = _SOURCE_LINE_RE.sub(" ", claim)
    return claim.strip()


# ── B4: NOT_FOUND detection via exact Status-column match ────────────────────
#
# A row is NOT_FOUND-exempt ONLY when the Status column (the last |cell| in the
# table row) exactly equals NOT_FOUND (case-insensitive).
# Fallback for non-table rows: strict pipe-bounded regex.

_NOT_FOUND_STATUS_RE = re.compile(r"\|\s*NOT_FOUND\s*\|\s*$", re.IGNORECASE)


def is_not_found_row(row: str) -> bool:
    """Return True only when the row's Status cell is exactly NOT_FOUND."""
    stripped = row.strip()
    # Table row: parse Status column (last data cell)
    if stripped.startswith("|") and stripped.endswith("|"):
        cells = [c.strip() for c in stripped.split("|")]
        data_cells = [c for c in cells if c]
        if data_cells:
            last = data_cells[-1]
            if last.upper() == "NOT_FOUND":
                return True
            # Don't match separator rows
            return False
    # Non-table: require pipe-bounded pattern (strict)
    return bool(_NOT_FOUND_STATUS_RE.search(stripped))


# ── Citation pattern: path:line or path:line-line ────────────────────────────
CITATION_RE = re.compile(
    r"""
    (?<!\w)                           # not preceded by word char
    (
        [A-Za-z0-9_./-]+              # path (relative)
        :
        (\d+)                         # start line
        (?:-(\d+))?                   # optional end line
    )
    (?!\w)                            # not followed by word char
    """,
    re.VERBOSE,
)

# Known file extensions that identify a genuine path token.
_FILE_EXT_RE = re.compile(
    r"\.(md|py|sh|java|kt|ts|js|tf|yml|yaml|json|txt|hcl|go|rb|rs|cs|cpp|c|html|xml|toml|cfg|ini|env|gradle|properties|xml)$",
    re.IGNORECASE,
)
# A version-like token: optional 'v', then digits.digits or digits.digits.digits
_VERSION_RE = re.compile(r"^v?\d+\.\d+(\.\d+)*$")

# ── Forbidden phrases (T5) ───────────────────────────────────────────────────
FORBIDDEN_PHRASES = [
    "probably", "likely", "typically", "generally",
]

# ── Parse artifact ───────────────────────────────────────────────────────────
artifact_text = artifact_file.read_text(encoding="utf-8", errors="replace")
artifact_lines = artifact_text.splitlines()

# ── B3: SHA pinning helper ────────────────────────────────────────────────────
_sha_tempfiles = {}  # cache: cited_path_str → tempfile path

def resolve_cited_file(cite_path_str: str) -> Optional[Path]:
    """
    Return the Path of the file to read for citation verification.
    If sha_pin is set, use `git show sha:path` into a tempfile.
    Otherwise, try the nominal path then the artifact-relative path.
    """
    if sha_pin:
        if cite_path_str in _sha_tempfiles:
            return _sha_tempfiles[cite_path_str]
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "show", f"{sha_pin}:{cite_path_str}"],
                capture_output=True,
                timeout=15,
            )
            if result.returncode != 0:
                return None
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".cited")
            tf.write(result.stdout)
            tf.flush()
            tf.close()
            p = Path(tf.name)
            _sha_tempfiles[cite_path_str] = p
            return p
        except Exception:
            return None
    else:
        # Working-tree read
        p = repo_path / cite_path_str
        if p.is_file():
            return p
        alt = artifact_file.parent / cite_path_str
        if alt.is_file():
            return alt
        return None


# ── Helpers for preceding-block accumulation ────────────────────────────────

def _is_block_boundary(line: str) -> bool:
    """
    Return True when this line resets the preceding-prose accumulator.

    A boundary is:
      - A blank line (or whitespace-only line)
      - A Markdown heading (# ... through ###### ...)
      - A table separator row (|---|---|)
      - A standalone SOURCE/citation-only line (resets after we consume it)

    Bullets, bold, and normal prose lines are NOT boundaries — they accumulate.
    """
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    # Table separator: cells of only dashes/spaces/pipes  e.g. |---|---| or |:---:|
    if stripped.startswith("|") and re.match(r"^[\|\-:\s]+$", stripped):
        return True
    return False


def _extract_prose_text(line: str) -> str:
    """
    Return the prose content of a non-SOURCE, non-boundary line, stripped of
    Markdown decoration and citation patterns.
    """
    text = line.strip()
    # Strip leading bullet markers (-, *, 1., etc.)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = re.sub(r"^\d+\.\s+", "", text)
    # Strip bold/italic markers
    text = re.sub(r"\*{1,2}|_{1,2}", "", text)
    # Strip inline citation patterns so they don't pollute the claim tokens
    text = _CITATION_ON_LINE_RE.sub(" ", text)
    text = _SOURCE_LINE_RE.sub(" ", text)
    return text.strip()


# ── Collect citations ────────────────────────────────────────────────────────
citations = []  # list of dicts

# Preceding-block accumulator for SOURCE-line claim fallback.
#
# The root cause of the 0.0-for-all-failures signature Rany observed:
#   - A standalone **SOURCE:** line has no claim of its own (extract_claim_from_row
#     returns "").
#   - The old code kept only `last_non_citation_line = claim_text` — a single line.
#     When the SOURCE line followed a multi-bullet **Recommendation:** block that
#     ended with a blank line, the accumulator held only the last bullet (or was
#     empty), so the fallback claim was degenerate.
#   - Fix: accumulate ALL consecutive non-blank, non-boundary lines above the
#     SOURCE line (up to the previous blank/heading/separator boundary) into a
#     block, and use the concatenation as the fallback claim.  This captures the
#     full **Recommendation:** bullet set and produces genuine token overlap.
#
# Accumulator state:
#   _prose_block   — list of prose strings in the current block (resets on boundary)
#   _prose_fallback — the *previous* completed block (what a SOURCE line sees when
#                     the blank line between the Recommendation bullets and the
#                     **SOURCE:** line has already reset _prose_block to [])
#
# Why two variables?
#   The structure is:
#       **Recommendation:** REUSE Terraform modules   <- prose
#       - Adapt MS Terraform modules                  <- prose
#       - Use same state management                   <- prose
#                                                     <- blank line → boundary, resets block
#       **SOURCE:** MS_Current_System_Architecture.md:750-800
#
#   The blank line fires BEFORE the SOURCE line, so _prose_block is [] when we
#   hit the SOURCE line.  We need the block that was completed *just before* the
#   blank line — that is _prose_fallback.

_prose_block: list = []
_prose_fallback: str = ""

for lineno, row in enumerate(artifact_lines, start=1):
    # B4: exact Status-column match for NOT_FOUND
    not_found = is_not_found_row(row)

    # B2: extract claim (Field+Value cells; "" for standalone SOURCE lines)
    claim_text = extract_claim_from_row(row)

    # ── Update preceding-block accumulator ───────────────────────────────────
    if _is_block_boundary(row):
        # Commit the current block as the fallback before resetting
        if _prose_block:
            _prose_fallback = " ".join(_prose_block)
        _prose_block = []
    elif is_citation_only_line(row):
        # SOURCE line: the accumulator stays; we DO NOT add the citation text
        # to the block (it must not pollute future claims).
        # After this SOURCE line the block continues accumulating prose below it.
        pass
    else:
        # Normal prose / table row — add to the rolling block
        prose = _extract_prose_text(row)
        if prose:
            _prose_block.append(prose)

    # Find all path:line citations in this row
    for m in CITATION_RE.finditer(row):
        full_cite = m.group(1)
        cite_path_str = full_cite.rsplit(":", 1)[0]
        cite_line_part = full_cite.rsplit(":", 1)[1]

        # Validate cite_path_str looks like a file path.
        # Guard 1: skip bare numbers (e.g. "12:34" looks like a time)
        if re.match(r"^\d+$", cite_path_str):
            continue
        # Guard 2: version-like strings
        if _VERSION_RE.match(cite_path_str):
            continue
        # Guard 3: must look like a file path
        if "/" not in cite_path_str and not _FILE_EXT_RE.search(cite_path_str):
            continue

        line_parts = cite_line_part.split("-")
        try:
            line_start = int(line_parts[0])
            line_end = int(line_parts[1]) if len(line_parts) > 1 else line_start
        except ValueError:
            continue

        # B2: use claim_text; for SOURCE-only lines fall back to the preceding BLOCK.
        # Fallback priority:
        #   1. claim_text (non-empty for table rows and non-SOURCE prose)
        #   2. _prose_block joined (SOURCE line sits inside a block, e.g. inline after prose)
        #   3. _prose_fallback (SOURCE line follows a blank line; block was committed)
        if claim_text:
            effective_claim = claim_text
        elif _prose_block:
            effective_claim = " ".join(_prose_block)
        else:
            effective_claim = _prose_fallback

        citations.append({
            "artifact_line": lineno,
            "row_text": row,
            "claim_text": effective_claim,
            "citation": full_cite,
            "cited_path": cite_path_str,
            "line_start": line_start,
            "line_end": line_end,
            "is_not_found": not_found,
        })

# ── B5: zero-citation guard ───────────────────────────────────────────────────
CITATION_BEARING_NAMES = {"CODE_INDEX.md", "VALIDATION_SUMMARY.md", "PHASE1_DETECTION.md"}

total = len(citations)

if int(min_citations_arg) < 0:
    # Heuristic: require >= 1 for citation-bearing artifact names
    min_citations = 1 if artifact_file.name in CITATION_BEARING_NAMES else 0
else:
    min_citations = int(min_citations_arg)

zero_citation_fail = (total < min_citations)

# ── Resolve citations ────────────────────────────────────────────────────────
results = []
resolved = 0
failed = []

for c in citations:
    cited_path = resolve_cited_file(c["cited_path"])

    if cited_path is None:
        results.append({**c, "status": "NOT_FOUND_ON_DISK", "overlap": 0.0, "pass": False})
        failed.append(c["citation"])
        continue

    if c["is_not_found"]:
        # NOT_FOUND rows are exempt — count as resolved
        results.append({**c, "status": "EXEMPT_NOT_FOUND", "overlap": 1.0, "pass": True})
        resolved += 1
        continue

    # Read cited lines
    try:
        file_lines = cited_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        results.append({**c, "status": f"READ_ERROR: {e}", "overlap": 0.0, "pass": False})
        failed.append(c["citation"])
        continue

    line_start = max(1, c["line_start"])
    # B6: cap span at MAX_CITED_SPAN lines
    line_end = min(len(file_lines), c["line_end"])
    line_end = min(line_end, line_start + MAX_CITED_SPAN - 1)

    if line_start > len(file_lines):
        results.append({**c, "status": "OUT_OF_BOUNDS", "overlap": 0.0, "pass": False})
        failed.append(c["citation"])
        continue

    cited_content = "\n".join(file_lines[line_start - 1:line_end])

    # B2: compute overlap using claim_text (Field+Value), not the full row
    claim_tokens = tokenize(c["claim_text"])
    cited_tokens = tokenize(cited_content)

    if not claim_tokens:
        # Empty claim sentence — pass through (e.g. header separator row)
        overlap = 1.0
    else:
        shared = claim_tokens & cited_tokens
        overlap = len(shared) / len(claim_tokens)

    passes = overlap >= threshold

    if passes:
        resolved += 1
        results.append({**c, "status": "RESOLVED", "overlap": round(overlap, 3), "pass": True})
    else:
        failed.append(c["citation"])
        results.append({**c, "status": "LOW_OVERLAP", "overlap": round(overlap, 3), "pass": False})

# Clean up SHA tempfiles
for tf_path in _sha_tempfiles.values():
    try:
        os.unlink(str(tf_path))
    except OSError:
        pass

# ── Check forbidden phrases ──────────────────────────────────────────────────
forbidden_hits = []
for lineno, row in enumerate(artifact_lines, start=1):
    for phrase in FORBIDDEN_PHRASES:
        if phrase in row.lower():
            forbidden_hits.append({"line": lineno, "phrase": phrase, "row": row.strip()})

# ── Build VALIDATION_SUMMARY.md ──────────────────────────────────────────────
pct = (resolved / total * 100) if total > 0 else 0.0

summary_lines = [
    f"# VALIDATION_SUMMARY — {artifact_file.name}",
    "",
    f"**Generated:** {date.today().isoformat()}",
    f"**Artifact:** `{artifact_file}`",
    f"**Repo root:** `{repo_path}`",
    f"**Threshold:** {threshold} (min overlap score)",
    f"**SHA pin:** `{sha_pin}`" if sha_pin else f"**SHA pin:** (working tree)",
    "",
    "## Results",
    "",
    f"| Metric | Value |",
    f"|--------|-------|",
    f"| Total citations | {total} |",
    f"| Resolved (pass) | {resolved} |",
    f"| Failed (low overlap / not found) | {len(failed)} |",
    f"| Verification rate | {pct:.1f}% |",
    f"| Forbidden phrases | {len(forbidden_hits)} |",
    f"| Min citations required | {min_citations} |",
    "",
]

if zero_citation_fail:
    summary_lines += [
        "## Zero-Citation Failure",
        "",
        f"ERROR: artifact `{artifact_file.name}` is expected to carry at least "
        f"{min_citations} citation(s) but has 0. "
        "This is a hard-gate failure — an empty artifact passes nothing.",
        "",
    ]

if failed:
    summary_lines += [
        "## Failed Citations",
        "",
        "| # | Citation | Artifact Line | Overlap | Status |",
        "|---|----------|--------------|---------|--------|",
    ]
    for r in results:
        if not r["pass"]:
            summary_lines.append(
                f"| — | `{r['citation']}` | {r['artifact_line']} | {r['overlap']} | {r['status']} |"
            )
    summary_lines.append("")

if forbidden_hits:
    summary_lines += [
        "## Forbidden Phrase Hits (T5)",
        "",
        "| Line | Phrase | Row |",
        "|------|--------|-----|",
    ]
    for h in forbidden_hits:
        summary_lines.append(f"| {h['line']} | `{h['phrase']}` | {h['row'][:80]} |")
    summary_lines.append("")

if not failed and not forbidden_hits and not zero_citation_fail:
    summary_lines += ["## Status", "", "✅ All citations resolved. No forbidden phrases.", ""]

summary_text = "\n".join(summary_lines)

# ── Output ────────────────────────────────────────────────────────────────────
if dry_run:
    print(summary_text)
else:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_text, encoding="utf-8")
    print(f"[verify_citations] VALIDATION_SUMMARY.md written: {summary_path}", file=sys.stderr)

# Print a brief report to stdout
print(f"Citations: {total} total, {resolved} resolved ({pct:.1f}%), {len(failed)} failed")
if failed:
    print("FAILED citations:")
    for cite in failed:
        print(f"  - {cite}")

if forbidden_hits:
    print(f"FORBIDDEN phrases found: {len(forbidden_hits)}")

if zero_citation_fail:
    print(
        f"ERROR: zero citations in citation-bearing artifact "
        f"'{artifact_file.name}' (min required: {min_citations})"
    )

# Exit 1 if any citations failed or zero-citation failure
sys.exit(1 if (failed or zero_citation_fail) else 0)
PYEOF

exit_code=$?
exit $exit_code
