#!/usr/bin/env bash
# extract_express.sh — Node/Express + TypeScript code-index extractor
#
# Usage:  bash scripts/onboarding/extract_express.sh <REPO_PATH> [SRC_ROOTS...]
#
# SRC_ROOTS (optional): space-separated list of source root directories detected
# by REPO_ONBOARDING_AGENT.md Step 3.5.  If omitted the extractor scans:
#   1. $REPO_PATH/src (if present)
#   2. $REPO_PATH root with node_modules/build/dist/target excluded
# This fixes No-src/ repos: repos without a src/ directory now emit records.
#
# Stdout contract: one JSON-lines record per discovered symbol, e.g.:
#   {"path":"src/routes/users.ts","line":10,"kind":"endpoint","identifier":"GET /api/users"}
#
# kind values:
#   module        — top-level src/ subdirectory treated as a module
#   entry_point   — express() / new NestFactory instantiation
#   endpoint      — router.get/post/put/delete/patch(  or app.get/post/…
#   config        — process.env.KEY reference
#   integration   — axios / fetch / got / http/https .request calls
#   test_location — *.spec.ts / *.test.ts / *.spec.js / *.test.js
#
# Fail-closed: entries without a verifiable file:line are SILENTLY DROPPED.
# All env-var parsing uses `cut -d'=' -f2-` so values containing `=` are not truncated.
# Exit 0 always.
#
# Bash 3.2 compatibility:
#   - No ${var,,} / ${var^^}  → use $(echo "$var" | tr '[:upper:]' '[:lower:]')
#   - No mapfile / readarray  → use while-read loops
#   - No associative arrays   → not needed here
#
# JSON serialization: all emit() calls delegate to python3 json.dumps so that
# identifiers containing ", \, or % (route paths, package names) produce valid
# JSON. printf-based serialization is deliberately NOT used.
#
# Requires: bash 3.2+, grep, find, python3 3.9+

set -euo pipefail
REPO_PATH="${1:?Usage: extract_express.sh <REPO_PATH> [SRC_ROOTS...]}"
REPO_PATH="$(realpath "$REPO_PATH")"
shift || true

emit() {
  local p="$1" l="$2" k="$3" id="$4"
  [[ -z "$p" || -z "$l" || -z "$k" || -z "$id" ]] && return 0
  python3 -c "
import json, sys
p, l, k, i = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    line_int = int(l)
except ValueError:
    sys.exit(0)
if line_int <= 0:
    sys.exit(0)
print(json.dumps({'path': p, 'line': line_int, 'kind': k, 'identifier': i}))
" "$p" "$l" "$k" "$id" 2>/dev/null || true
}

rel() { echo "${1#"$REPO_PATH/"}"; }

# ── Resolve source scan roots (No-src/ repos fix) ──────────────────────────────────────
# Build SRC_DIRS as a bash 3.2-compatible array of directories to scan for .ts/.js files.
# Priority order:
#   1. Explicit SRC_ROOTS passed as extra arguments (from PHASE1_DETECTION.md)
#   2. $REPO_PATH/src if it exists
#   3. Fall back to $REPO_PATH (repo root with excludes)
#
# the design record fix: SRC_DIRS was a space-separated string, which word-splits on paths
# containing a space, producing 0 records and exit 0 (silent data loss).  Converted
# to a bash array using bash 3.2-compatible syntax (no mapfile, no associative arrays).

SRC_DIRS=()
if [[ $# -gt 0 ]]; then
  # Explicit roots supplied
  for d in "$@"; do
    [[ -d "$d" ]] && SRC_DIRS+=("$d")
  done
fi
if [[ ${#SRC_DIRS[@]} -eq 0 ]]; then
  if [[ -d "$REPO_PATH/src" ]]; then
    SRC_DIRS=("$REPO_PATH/src")
  else
    SRC_DIRS=("$REPO_PATH")
  fi
fi

# ── modules (top-level src/ subdirectories) ───────────────────────────────────
if [[ -d "$REPO_PATH/src" ]]; then
  while IFS= read -r d; do
    [[ -d "$d" ]] || continue
    emit "src/$(basename "$d")" 1 "module" "$(basename "$d")"
  done < <(find "$REPO_PATH/src" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)
fi

# package.json name as module root
if [[ -f "$REPO_PATH/package.json" ]]; then
  pkg_name=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get('name',''))
except Exception:
    pass
" "$REPO_PATH/package.json" 2>/dev/null || true)
  [[ -n "$pkg_name" ]] && emit "package.json" 1 "module" "$pkg_name"
fi

# ── entry points ─────────────────────────────────────────────────────────────
for scan_dir in "${SRC_DIRS[@]}"; do
  [[ -d "$scan_dir" ]] || continue
  while IFS= read -r match; do
    f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"
    [[ -z "$f" || -z "$l" ]] && continue
    emit "$(rel "$f")" "$l" "entry_point" "express()"
  done < <(grep -rn "express()" "$scan_dir" \
            --include="*.ts" --include="*.js" 2>/dev/null \
           | grep -v "node_modules" || true)

  while IFS= read -r match; do
    f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"
    [[ -z "$f" || -z "$l" ]] && continue
    emit "$(rel "$f")" "$l" "entry_point" "NestFactory.create()"
  done < <(grep -rn "NestFactory\.create\b" "$scan_dir" \
            --include="*.ts" 2>/dev/null \
           | grep -v "node_modules" || true)
done

# ── HTTP endpoints ────────────────────────────────────────────────────────────
# Bash 3.2 compat: replace ${method^^} with tr uppercase; use explicit loop body
for method in get post put delete patch; do
  # bash 3.2 compatible uppercase: use tr
  http_method=$(echo "$method" | tr '[:lower:]' '[:upper:]')

  for scan_dir in "${SRC_DIRS[@]}"; do
    [[ -d "$scan_dir" ]] || continue

    # Express-style: (router|app).get('/path'
    while IFS= read -r match; do
      f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
      [[ -z "$f" || -z "$l" ]] && continue
      path_val=$(echo "$content" | grep -oE "'[^']*'" | head -1 | tr -d "'" || \
                 echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
      [[ -z "$path_val" ]] && path_val="(dynamic)"
      emit "$(rel "$f")" "$l" "endpoint" "${http_method} ${path_val}"
    done < <(grep -irn "\.\(${method}\)(['\"]" "$scan_dir" \
              --include="*.ts" --include="*.js" 2>/dev/null \
             | grep -v "node_modules" || true)

    # NestJS-style: @Get('/path')  @Post('/path')
    # bash 3.2 compatible: capitalise first char using cut/tr
    first_upper=$(echo "${method:0:1}" | tr '[:lower:]' '[:upper:]')
    rest_of_method="${method:1}"
    ann="${first_upper}${rest_of_method}"
    while IFS= read -r match; do
      f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
      [[ -z "$f" || -z "$l" ]] && continue
      path_val=$(echo "$content" | grep -oE "'[^']*'" | head -1 | tr -d "'" || \
                 echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
      [[ -z "$path_val" ]] && path_val="(unmapped)"
      emit "$(rel "$f")" "$l" "endpoint" "${http_method} ${path_val}"
    done < <(grep -rn "@${ann}(['\"]" "$scan_dir" \
              --include="*.ts" 2>/dev/null \
             | grep -v "node_modules" || true)
  done
done

# ── config surface (process.env.KEY) ─────────────────────────────────────────
for scan_dir in "${SRC_DIRS[@]}"; do
  [[ -d "$scan_dir" ]] || continue
  while IFS= read -r match; do
    f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
    [[ -z "$f" || -z "$l" ]] && continue
    key=$(echo "$content" | grep -oE 'process\.env\.[A-Za-z_][A-Za-z0-9_]*' | head -1 || true)
    [[ -z "$key" ]] && continue
    emit "$(rel "$f")" "$l" "config" "$key"
  done < <(grep -rn "process\.env\." "$scan_dir" \
            --include="*.ts" --include="*.js" 2>/dev/null \
           | grep -v "node_modules" || true)
done

# .env file keys (use cut -d'=' -f1 for key extraction)
if [[ -f "$REPO_PATH/.env" ]]; then
  lineno=1
  while IFS= read -r line; do
    # Non-comment, non-empty lines with = (use cut -d'=' -f1 for key only)
    if echo "$line" | grep -qE '^[^#][A-Za-z_][A-Za-z0-9_]*='; then
      key=$(echo "$line" | cut -d'=' -f1)
      [[ -n "$key" ]] && emit ".env" "$lineno" "config" "$key"
    fi
    lineno=$((lineno + 1))
  done < "$REPO_PATH/.env"
fi

# ── integration points ────────────────────────────────────────────────────────
for client in axios fetch got "http\.request" "https\.request"; do
  for scan_dir in "${SRC_DIRS[@]}"; do
    [[ -d "$scan_dir" ]] || continue
    while IFS= read -r match; do
      f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
      [[ -z "$f" || -z "$l" ]] && continue
      hint=$(echo "$content" | grep -oE "(axios|fetch|got|http|https)\.[a-zA-Z]+" | head -1 || \
             echo "${client%%\\.*}")
      emit "$(rel "$f")" "$l" "integration" "$hint"
    done < <(grep -rn "${client}" "$scan_dir" \
              --include="*.ts" --include="*.js" 2>/dev/null \
             | grep -v "node_modules" || true)
  done
done

# ── test locations ────────────────────────────────────────────────────────────
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  emit "$(rel "$f")" 1 "test_location" "$(basename "$f")"
done < <(find "$REPO_PATH" \
          \( -name "*.spec.ts" -o -name "*.test.ts" \
          -o -name "*.spec.js" -o -name "*.test.js" \) \
         ! -path "*/node_modules/*" 2>/dev/null | head -50)

exit 0
