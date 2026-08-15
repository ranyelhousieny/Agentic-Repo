#!/usr/bin/env bash
# extract_spring_boot.sh — Spring Boot code-index extractor
#
# Usage:  bash scripts/onboarding/extract_spring_boot.sh <REPO_PATH>
#
# Stdout contract: one JSON-lines record per discovered symbol, e.g.:
#   {"path":"src/main/java/Foo.java","line":12,"kind":"endpoint","identifier":"GET /api/users"}
#
# kind values:
#   module        — top-level package / Maven module
#   entry_point   — @SpringBootApplication class
#   endpoint      — @GetMapping / @PostMapping / @PutMapping / @DeleteMapping / @PatchMapping
#   config        — @Value / @ConfigurationProperties key
#   integration   — @FeignClient / RestTemplate / WebClient / @KafkaListener / @RabbitListener
#   test_location — test source root / test class
#
# Fail-closed: entries without a verifiable file:line are SILENTLY DROPPED.
# All env-var parsing uses `cut -d'=' -f2-` per Rule 11 (TOKEN TRUNCATION BUG).
# Exit 0 always (non-fatal extraction errors are swallowed; partial output is valid).
#
# JSON serialization: all emit() calls delegate to python3 json.dumps so that
# identifiers containing ", \, or % (route paths, committer names, package names)
# produce valid JSON. printf-based serialization is deliberately NOT used.
#
# Requires: bash 3.2+, grep, find, sed, awk, python3 3.9+

set -euo pipefail
REPO_PATH="${1:?Usage: extract_spring_boot.sh <REPO_PATH> [SRC_ROOTS...]}"
REPO_PATH_RAW="$REPO_PATH"
REPO_PATH="$(realpath "$REPO_PATH")"
shift || true

# ── Resolve source scan roots (B16 fix) ──────────────────────────────────────
# Build SRC_DIR: directory to scan for .java/.kt source files.
# Priority order:
#   1. Explicit SRC_ROOTS passed as extra arguments (from PHASE1_DETECTION.md)
#   2. $REPO_PATH/src if it exists
#   3. Fall back to $REPO_PATH (repo root, grep's --exclude-dir handles noise)
if [[ $# -gt 0 ]]; then
  SRC_DIR="$1"  # Use first explicit root for Spring scanning
  shift || true
elif [[ -d "$REPO_PATH/src" ]]; then
  SRC_DIR="$REPO_PATH/src"
else
  SRC_DIR="$REPO_PATH"
fi

# ── helpers ──────────────────────────────────────────────────────────────────
# emit: serialize to JSON-lines via python3 so special chars in args are safe.
emit() {
  local p="$1" l="$2" k="$3" id="$4"
  [[ -z "$p" || -z "$l" || -z "$k" || -z "$id" ]] && return 0   # fail-closed
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

# Strip both the given prefix and the physically-resolved one: on macOS /tmp is a
# symlink to /private/tmp, and a caller-passed SRC_DIR can surface either form —
# an absolute path that survives into a record is unverifiable by the T3 gate.
REPO_REALPATH="$(cd "$REPO_PATH" 2>/dev/null && pwd -P || true)"
rel() { local p="$1"; p="${p#"$REPO_PATH/"}"; p="${p#"$REPO_REALPATH/"}"; [[ -n "$REPO_PATH_RAW" ]] && p="${p#"$REPO_PATH_RAW/"}"; echo "$p"; }

# ── modules ──────────────────────────────────────────────────────────────────
# Each pom.xml that isn't the root signals a Maven sub-module
while IFS= read -r f; do
  dir="$(dirname "$f")"
  module_name="$(basename "$dir")"
  # Cite the <artifactId> line, not line 1 (an XML prolog carries no identifier
  # tokens, so a :1 citation always fails the T3 overlap gate); the artifactId
  # value IS the Maven module name, so prefer it as the identifier.
  aid_line=$(grep -n "<artifactId>" "$f" 2>/dev/null | head -1 | cut -d: -f1 || true)
  aid=$(grep -o "<artifactId>[^<]*</artifactId>" "$f" 2>/dev/null | head -1 | sed 's/<[^>]*>//g' || true)
  emit "$(rel "$f")" "${aid_line:-1}" "module" "${aid:-$module_name}"
done < <(find "$REPO_PATH" -name "pom.xml" ! -path "$REPO_PATH/pom.xml" 2>/dev/null)

# Root pom.xml is always the top-level module
if [[ -f "$REPO_PATH/pom.xml" ]]; then
  aid_line=$(grep -n "<artifactId>" "$REPO_PATH/pom.xml" 2>/dev/null | head -1 | cut -d: -f1 || true)
  aid=$(grep -o "<artifactId>[^<]*</artifactId>" "$REPO_PATH/pom.xml" 2>/dev/null | head -1 | sed 's/<[^>]*>//g' || true)
  emit "pom.xml" "${aid_line:-1}" "module" "${aid:-root}"
fi

# ── entry points (@SpringBootApplication) ────────────────────────────────────
while IFS= read -r match; do
  f="${match%%:*}"; l="${match#*:}"; l="${l%%:*}"
  [[ -z "$f" || -z "$l" ]] && continue
  class=$(grep -m1 'public class ' "$f" 2>/dev/null | sed 's/.*public class \([A-Za-z0-9_]*\).*/\1/' || true)
  [[ -z "$class" ]] && class="$(basename "${f%.java}")"
  emit "$(rel "$f")" "$l" "entry_point" "$class"
done < <(grep -rn "@SpringBootApplication" "$SRC_DIR/" \
          --include="*.java" --include="*.kt" \
          --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="target" \
          2>/dev/null || true)

# ── HTTP endpoints ────────────────────────────────────────────────────────────
# NOTE: @RequestMapping is intentionally excluded here — it is used at both
# the class level (base path) and the method level. Emitting it as an endpoint
# for every controller class produces phantom rows and pollutes the inventory.
# Class-level @RequestMapping is captured as a config entry (base-path) instead.
for ann in GetMapping PostMapping PutMapping DeleteMapping PatchMapping; do
  http_method=""
  case "$ann" in
    GetMapping)    http_method="GET"    ;;
    PostMapping)   http_method="POST"   ;;
    PutMapping)    http_method="PUT"    ;;
    DeleteMapping) http_method="DELETE" ;;
    PatchMapping)  http_method="PATCH"  ;;
  esac
  while IFS= read -r match; do
    f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
    [[ -z "$f" || -z "$l" ]] && continue
    # Extract path from annotation value, e.g. @GetMapping("/api/v1/users")
    path_val=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
    [[ -z "$path_val" ]] && path_val="(unmapped)"
    emit "$(rel "$f")" "$l" "endpoint" "${http_method} ${path_val}"
  done < <(grep -rn "@${ann}" "$SRC_DIR/" \
            --include="*.java" --include="*.kt" \
            --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="target" \
            2>/dev/null || true)
done

# Class-level @RequestMapping → base-path config record (not an endpoint row)
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  path_val=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
  [[ -z "$path_val" ]] && continue   # no path value → nothing useful to emit
  emit "$(rel "$f")" "$l" "config" "@RequestMapping base-path: ${path_val}"
done < <(grep -rn "@RequestMapping" "$SRC_DIR/" \
          --include="*.java" --include="*.kt" \
          --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="target" \
          2>/dev/null || true)

# ── config surface (@Value / @ConfigurationProperties) ───────────────────────
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  key=$(echo "$content" | grep -oE '\$\{[^}]+\}' | head -1 || true)
  # No ${...} key means this is not a Spring config injection at all — on repos
  # using lombok, @Value is lombok.Value on classes, and emitting "(inline)"
  # for it produced unverifiable noise records (identifier matches nothing).
  [[ -z "$key" ]] && continue
  emit "$(rel "$f")" "$l" "config" "$key"
done < <(grep -rn "@Value" "$SRC_DIR/" \
          --include="*.java" --include="*.kt" \
          --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="target" \
          2>/dev/null || true)

while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  prefix=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
  [[ -z "$prefix" ]] && prefix="(unmapped)"
  emit "$(rel "$f")" "$l" "config" "@ConfigurationProperties(${prefix})"
done < <(grep -rn "@ConfigurationProperties" "$SRC_DIR/" \
          --include="*.java" --include="*.kt" \
          --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="target" \
          2>/dev/null || true)

# application.properties / application.yml surface
# Try standard Maven path; these files are conventionally in src/main/resources
for props_file in \
  "$REPO_PATH/src/main/resources/application.properties" \
  "$REPO_PATH/src/main/resources/application.yml" \
  "$REPO_PATH/src/main/resources/application.yaml"; do
  [[ -f "$props_file" ]] || continue
  lineno=1
  while IFS= read -r line; do
    # Match non-comment key=value or key: value lines
    if [[ "$line" =~ ^[^#][a-zA-Z][a-zA-Z0-9._-]*(=|:) ]]; then
      key="${line%%[=:]*}"
      key="$(echo "$key" | xargs)"
      [[ -n "$key" ]] && emit "$(rel "$props_file")" "$lineno" "config" "$key"
    fi
    (( lineno++ ))
  done < "$props_file"
done

# ── integration points ────────────────────────────────────────────────────────
for ann in FeignClient KafkaListener RabbitListener; do
  while IFS= read -r match; do
    f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
    [[ -z "$f" || -z "$l" ]] && continue
    name=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
    [[ -z "$name" ]] && name="$ann"
    emit "$(rel "$f")" "$l" "integration" "@${ann}(${name})"
  done < <(grep -rn "@${ann}" "$SRC_DIR/" \
            --include="*.java" --include="*.kt" \
            --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="target" \
            2>/dev/null || true)
done

# RestTemplate / WebClient usage
for client in RestTemplate WebClient; do
  while IFS= read -r match; do
    f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"
    [[ -z "$f" || -z "$l" ]] && continue
    emit "$(rel "$f")" "$l" "integration" "$client"
  done < <(grep -rn "${client}" "$SRC_DIR/" \
            --include="*.java" --include="*.kt" \
            --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir="target" \
            2>/dev/null || true)
done

# ── test locations ────────────────────────────────────────────────────────────
# Emit one entry per test directory root rather than every test file
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  b="$(basename "$f")"; b="${b%.java}"; b="${b%.kt}"
  # The identifier IS the class name, so cite the declaration line first — an
  # annotation line (@Test, @ExtendWith(PactConsumerTestExt.class), ...) does not
  # carry the class name and always fails the T3 overlap gate. Annotation hits are
  # only a fallback for files whose declaration grep misses.
  l=$(grep -n "class ${b}\|object ${b}\|interface ${b}" "$f" 2>/dev/null | head -1 | cut -d: -f1 || true)
  if [[ -z "$l" ]]; then l=$(grep -n "@Test\|@SpringBootTest\|@ExtendWith" "$f" 2>/dev/null | head -1 | cut -d: -f1 || true); fi
  emit "$(rel "$f")" "${l:-1}" "test_location" "$b"
done < <(find "$REPO_PATH" -path "*/test*" \
          \( -name "*.java" -o -name "*.kt" \) 2>/dev/null | head -50)

exit 0
