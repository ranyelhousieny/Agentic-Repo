#!/usr/bin/env bash
# extract_git_ownership.sh — git-history ownership extractor  (ownership schema v2)
#
# Usage:  bash scripts/onboarding/extract_git_ownership.sh <REPO_PATH> [--months N]
#
# Stdout contract (OWNERSHIP schema v2 — differs from code-symbol extractors):
#
#   {
#     "area": "<area>",
#     "original_architect": "Name <email>",    # all-time top committer (bot-filtered)
#     "current_maintainer": "Name <email>",    # most recent committer (bot-filtered)
#     "codeowners_entry": "<entry or null>",   # from CODEOWNERS file, if present
#     "catalog_info_owner": "<owner or null>", # from catalog-info.yaml spec.owner, if present
#     "agreement": "AGREE|CONFLICTING|SINGLE_SOURCE",
#     "derivation_date": "YYYY-MM-DD",
#     "top_committers": ["Name <email>", ...], # kept for backward-compat with merge_sme_contacts.py
#     "last_touched_date": "YYYY-MM-DD",
#     "commit_count": <int>
#   }
#
# This script has a DIFFERENT schema from the four code-symbol extractors
# (extract_spring_boot.sh, extract_fastapi.py, extract_express.sh,
# extract_terraform.sh) which emit {path,line,kind,identifier}.
# See scripts/onboarding/README.md for the full contract breakdown.
#
# Ownership granularity: records are emitted PER TOP-LEVEL AREA (directory).
# The repo scope is NEVER labelled "sole author" or "single owner" — those
# labels apply only to individual paths/areas where the per-path shortlog
# shows exactly one human committer.  A repo may be multi-owner overall
# while having some single-owner sub-paths.  Downstream consumers MUST NOT
# aggregate these per-area records into a repo-level sole-author claim.
#
# Bot filtering:
#   Reads scripts/onboarding/bot_identities.txt (co-located with this script).
#   Excludes matching committers from top_committers, original_architect,
#   current_maintainer, AND from commit_count.
#   Pattern rules: see bot_identities.txt header for EMAIL_GLOB vs NAME_SUBSTR semantics.
#
# Agreement column semantics:
#   AGREE          — git-derived owner AND at least one of CODEOWNERS/catalog-info
#                    name the same owner (case-insensitive email or name substring).
#   CONFLICTING    — git-derived owner AND at least one source present but they disagree.
#   SINGLE_SOURCE  — only git history available (no CODEOWNERS entry, no catalog-info
#                    spec.owner, or both are absent/empty for this area).
#
# Options:
#   --months N   Look-back window in months (default: 12).  Uses `--after=N.months.ago`
#                in git-log so it works on all git versions.
#
# Fail-closed: areas with zero (human) commits in the window are SILENTLY DROPPED.
# All env-var parsing uses `cut -d'=' -f2-` so values containing `=` are not truncated.
# Exit 0 always — partial output is valid.
# Requires: git (on PATH), bash 3.2+, python3 3.9+ (for JSON serialization), awk, sort, head.

set -euo pipefail
REPO_PATH="${1:?Usage: extract_git_ownership.sh <REPO_PATH> [--months N]}"
REPO_PATH="$(realpath "$REPO_PATH")"

MONTHS=12
shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --months) MONTHS="${2:?--months requires a value}"; shift 2 ;;
    *) shift ;;
  esac
done

AFTER="${MONTHS}.months.ago"

# Locate the bot-identities deny-list co-located with this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_IDENTITIES_FILE="${SCRIPT_DIR}/bot_identities.txt"

# Verify this is a git repo
if ! git -C "$REPO_PATH" rev-parse --is-inside-work-tree &>/dev/null; then
  python3 -c "
import json, datetime
print(json.dumps({
    'area': '(not a git repo)',
    'original_architect': None,
    'current_maintainer': None,
    'codeowners_entry': None,
    'catalog_info_owner': None,
    'agreement': 'SINGLE_SOURCE',
    'derivation_date': datetime.date.today().isoformat(),
    'top_committers': [],
    'last_touched_date': '',
    'commit_count': 0,
}))
" >&2
  exit 0
fi

# ── Read static ownership sources once (CODEOWNERS + catalog-info) ────────────
# CODEOWNERS: emit as-is, keyed by path pattern
CODEOWNERS_PATH=""
for candidate in "$REPO_PATH/CODEOWNERS" "$REPO_PATH/.github/CODEOWNERS" "$REPO_PATH/docs/CODEOWNERS"; do
  if [[ -f "$candidate" ]]; then
    CODEOWNERS_PATH="$candidate"
    break
  fi
done

# catalog-info.yaml spec.owner (global, not per-area)
CATALOG_INFO_OWNER=""
if [[ -f "$REPO_PATH/catalog-info.yaml" ]]; then
  CATALOG_INFO_OWNER=$(python3 -c "
import sys
try:
    import yaml
    with open(sys.argv[1]) as f:
        d = yaml.safe_load(f)
    print(d.get('spec', {}).get('owner', '') or '')
except Exception:
    pass
" "$REPO_PATH/catalog-info.yaml" 2>/dev/null || true)
fi

TODAY_ISO=$(python3 -c "import datetime; print(datetime.date.today().isoformat())" 2>/dev/null || date +%Y-%m-%d)

# ── emit_area(): produce one JSON record per top-level area ──────────────────
emit_area() {
  local area="$1"
  local raw_log
  # Format: author name|author email|ISO-date
  raw_log=$(git -C "$REPO_PATH" log \
    --format='%an|%ae|%aI' \
    --after="${AFTER}" \
    -- "${area}" 2>/dev/null || true)

  [[ -z "$raw_log" ]] && return 0  # fail-closed: no commits → drop

  # ── Bot filtering via Python ──────────────────────────────────────────────
  # Outputs: filtered_log (same format, bots removed), then a blank line,
  # then the original_architect (all-time top committer), then current_maintainer.
  # All bot matching is case-insensitive.
  local filtered_json
  filtered_json=$(python3 - "$area" "$raw_log" "$CODEOWNERS_PATH" "$CATALOG_INFO_OWNER" "$TODAY_ISO" \
    "$BOT_IDENTITIES_FILE" "$REPO_PATH" "$AFTER" <<'PYEOF'
import fnmatch, json, os, re, subprocess, sys
from datetime import date

area              = sys.argv[1]
raw_log           = sys.argv[2]
codeowners_path   = sys.argv[3]
catalog_owner_val = sys.argv[4]
today_iso         = sys.argv[5]
bot_file          = sys.argv[6]
repo_path         = sys.argv[7]
after             = sys.argv[8]

# ── Load bot deny-list ────────────────────────────────────────────────────
bot_patterns = []
if os.path.isfile(bot_file):
    for raw in open(bot_file).read().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith('#'):
            continue
        bot_patterns.append(raw.lower())

def is_bot(name_email: str) -> bool:
    """Return True if name_email matches any bot pattern."""
    ne = name_email.lower()
    # Extract email portion for EMAIL_GLOB patterns
    m = re.search(r'<([^>]+)>', ne)
    email_part = m.group(1) if m else ne
    for pat in bot_patterns:
        if '@' in pat:
            # EMAIL_GLOB: match against email part
            if fnmatch.fnmatch(email_part, pat):
                return True
        else:
            # NAME_SUBSTR: match anywhere in full string
            if pat in ne:
                return True
    return False

# ── Parse incoming raw log ────────────────────────────────────────────────
entries = []  # (name_email, iso_date)
for line in raw_log.splitlines():
    line = line.strip()
    if not line:
        continue
    parts = line.split('|', 2)
    if len(parts) < 3:
        continue
    name, email, iso = parts[0], parts[1], parts[2]
    ne = f"{name} <{email}>"
    entries.append((ne, iso))

# Filter bots
human_entries = [(ne, iso) for ne, iso in entries if not is_bot(ne)]

if not human_entries:
    # All committers were bots — drop area
    sys.exit(0)

# ── Compute fields (Email-keyed dedup: key identity counter on lowercased email) ────────
# This ensures "asmith 14 commits" + "Alice Smith 5 commits" on the
# same email are counted as a single person (total 19), not two separate people.
commit_count = len(human_entries)

from collections import Counter, defaultdict

def email_key_of(ne: str) -> str:
    """Extract lowercased email from 'Name <email>', or lowercase whole string."""
    m = re.search(r'<([^>]+)>', ne)
    return m.group(1).lower() if m else ne.lower()

def name_of(ne: str) -> str:
    """Extract display name from 'Name <email>', or return whole string."""
    m = re.search(r'<', ne)
    return ne[:ne.index('<')].strip() if m else ne

# Dedup by lowercased email
email_commits = Counter()           # lowercased_email → commit count
email_to_names = defaultdict(Counter)  # lowercased_email → {display_name: count}

for ne, _ in human_entries:
    ek = email_key_of(ne)
    nm = name_of(ne)
    email_commits[ek] += 1
    email_to_names[ek][nm] += 1

def canonical_ne(email_k: str) -> str:
    """Return 'MostFrequentName <email>' for the given lowercased email."""
    best_name = email_to_names[email_k].most_common(1)[0][0]
    return f"{best_name} <{email_k}>"

# top 3 committers by deduplicated email frequency
top3_emails = [ek for ek, _ in email_commits.most_common(3)]
top3 = [canonical_ne(ek) for ek in top3_emails]

# original architect: most commits all-time (requires full history pass)
alltime_log = ""
try:
    r = subprocess.run(
        ["git", "-C", repo_path, "log", "--format=%an|%ae", "--", area],
        capture_output=True, text=True, timeout=60
    )
    alltime_log = r.stdout
except Exception:
    alltime_log = raw_log  # fallback

alltime_email_commits = Counter()
alltime_email_to_names = defaultdict(Counter)
for line in alltime_log.splitlines():
    line = line.strip()
    if not line:
        continue
    parts = line.split('|', 1)
    if len(parts) < 2:
        continue
    name_raw, email_raw = parts[0], parts[1]
    ne = f"{name_raw} <{email_raw}>"
    if is_bot(ne):
        continue
    ek = email_raw.lower()
    alltime_email_commits[ek] += 1
    alltime_email_to_names[ek][name_raw] += 1

if alltime_email_commits:
    top_email = alltime_email_commits.most_common(1)[0][0]
    best_alltime_name = alltime_email_to_names[top_email].most_common(1)[0][0]
    original_architect = f"{best_alltime_name} <{top_email}>"
else:
    original_architect = top3[0] if top3 else None

# current maintainer: most recent committer (use canonical form by email)
if human_entries:
    first_ne = human_entries[0][0]
    ek = email_key_of(first_ne)
    current_maintainer = canonical_ne(ek)
else:
    current_maintainer = None

# last touched date
last_touched = human_entries[0][1][:10] if human_entries else ""

# ── CODEOWNERS lookup for this area ──────────────────────────────────────
codeowners_entry = None
if codeowners_path and os.path.isfile(codeowners_path):
    # Match the most specific CODEOWNERS pattern for this area.
    # We walk all patterns and take the LAST match (git CODEOWNERS semantics).
    try:
        matched = None
        for raw_line in open(codeowners_path).read().splitlines():
            raw_line = raw_line.strip()
            if not raw_line or raw_line.startswith('#'):
                continue
            parts2 = raw_line.split(None, 1)
            if not parts2:
                continue
            pat = parts2[0]
            owners_str = parts2[1] if len(parts2) > 1 else ""
            # Normalise pattern: strip leading /
            pat_norm = pat.lstrip('/')
            area_norm = area.lstrip('.').lstrip('/')
            if fnmatch.fnmatch(area_norm, pat_norm) or \
               area_norm.startswith(pat_norm.rstrip('*')) or \
               pat_norm in ('', '*', '**'):
                matched = owners_str.strip()
        codeowners_entry = matched if matched else None
    except Exception:
        codeowners_entry = None

# ── Agreement column ─────────────────────────────────────────────────────
catalog_owner = catalog_owner_val.strip() if catalog_owner_val else None

def owners_agree(git_owner: str, other: str) -> bool:
    """Fuzzy match: share an email domain token or name token."""
    g = git_owner.lower()
    o = other.lower()
    # Direct substring
    if g in o or o in g:
        return True
    # Email match
    g_email_m = re.search(r'<([^>]+)>', g)
    o_tokens = re.findall(r'[\w.-]+', o)
    if g_email_m:
        g_email = g_email_m.group(1)
        for tok in o_tokens:
            if tok and tok in g_email:
                return True
    return False

sources_present = bool(codeowners_entry) or bool(catalog_owner)

if not sources_present:
    agreement = "SINGLE_SOURCE"
elif original_architect and (
    (codeowners_entry and owners_agree(original_architect, codeowners_entry)) or
    (catalog_owner and owners_agree(original_architect, catalog_owner))
):
    agreement = "AGREE"
else:
    agreement = "CONFLICTING"

# ── Emit JSON ─────────────────────────────────────────────────────────────
print(json.dumps({
    "area": area,
    "original_architect": original_architect,
    "current_maintainer": current_maintainer,
    "codeowners_entry": codeowners_entry,
    "catalog_info_owner": catalog_owner or None,
    "agreement": agreement,
    "derivation_date": today_iso,
    "top_committers": top3,
    "last_touched_date": last_touched,
    "commit_count": commit_count,
}))
PYEOF
  ) || true

  [[ -n "$filtered_json" ]] && echo "$filtered_json" || true
}

# ── iterate top-level directories ────────────────────────────────────────────
while IFS= read -r entry; do
  name="$(basename "$entry")"
  # Skip hidden dirs (.git, .github, .claude) and common non-code dirs
  [[ "$name" == .* ]] && continue
  [[ "$name" == "node_modules" || "$name" == "vendor" || "$name" == "dist" ]] && continue
  emit_area "$name"
done < <(find "$REPO_PATH" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort)

# Also emit a whole-repo summary for the root
emit_area "."

exit 0
