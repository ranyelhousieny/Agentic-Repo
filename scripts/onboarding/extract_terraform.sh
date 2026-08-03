#!/usr/bin/env bash
# extract_terraform.sh — Terraform code-index extractor
#
# Usage:  bash scripts/onboarding/extract_terraform.sh <REPO_PATH>
#
# Stdout contract: one JSON-lines record per discovered symbol, e.g.:
#   {"path":"main.tf","line":3,"kind":"module","identifier":"aws_vpc.main"}
#
# kind values:
#   module        — Terraform module block (module "name" { source = "..." })
#   entry_point   — root main.tf (the terraform { required_providers { } } block)
#   endpoint      — API Gateway / Lambda URL resource blocks
#   config        — variable "NAME" declaration
#   integration   — provider "NAME" / data "NAME" blocks referencing external services
#   test_location — .tftest.hcl / terratest *_test.go files
#
# Fail-closed: entries without a verifiable file:line are SILENTLY DROPPED.
# All env-var parsing uses `cut -d'=' -f2-` so values containing `=` are not truncated.
# Exit 0 always.
#
# JSON serialization: all emit() calls delegate to python3 json.dumps so that
# identifiers containing ", \, or % produce valid JSON. printf-based
# serialization is deliberately NOT used.
#
# Requires: bash 3.2+, grep, find, python3 3.9+

set -euo pipefail
REPO_PATH="${1:?Usage: extract_terraform.sh <REPO_PATH>}"
REPO_PATH="$(realpath "$REPO_PATH")"

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

# ── entry points (root terraform{} blocks) ────────────────────────────────────
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"
  [[ -z "$f" || -z "$l" ]] && continue
  emit "$(rel "$f")" "$l" "entry_point" "terraform{} root block"
done < <(grep -rn "^terraform\s*{" "$REPO_PATH" \
          --include="*.tf" 2>/dev/null || true)

# ── module blocks ─────────────────────────────────────────────────────────────
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  name=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
  [[ -z "$name" ]] && name="(unnamed)"
  emit "$(rel "$f")" "$l" "module" "module.${name}"
done < <(grep -rn "^module\s\+\"" "$REPO_PATH" \
          --include="*.tf" 2>/dev/null || true)

# ── variables (config surface) ────────────────────────────────────────────────
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  name=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
  [[ -z "$name" ]] && name="(unnamed)"
  emit "$(rel "$f")" "$l" "config" "var.${name}"
done < <(grep -rn "^variable\s\+\"" "$REPO_PATH" \
          --include="*.tf" 2>/dev/null || true)

# ── provider blocks (integration points) ─────────────────────────────────────
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  name=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
  [[ -z "$name" ]] && name="(unnamed)"
  emit "$(rel "$f")" "$l" "integration" "provider.${name}"
done < <(grep -rn "^provider\s\+\"" "$REPO_PATH" \
          --include="*.tf" 2>/dev/null || true)

# ── data source blocks (integration points — external lookups) ────────────────
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  # data "aws_ami" "ubuntu" { … }  → aws_ami.ubuntu
  ds=$(echo "$content" | grep -oE '"[^"]*"\s+"[^"]*"' | head -1 \
       | tr -d '"' | xargs | tr ' ' '.' || true)
  [[ -z "$ds" ]] && ds="data-source"
  emit "$(rel "$f")" "$l" "integration" "data.${ds}"
done < <(grep -rn "^data\s\+\"" "$REPO_PATH" \
          --include="*.tf" 2>/dev/null || true)

# ── API Gateway / Lambda endpoint resources ───────────────────────────────────
for res in "aws_api_gateway_resource" "aws_api_gateway_method" \
           "aws_lambda_function_url" "aws_apigatewayv2_route"; do
  while IFS= read -r match; do
    f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
    [[ -z "$f" || -z "$l" ]] && continue
    name=$(echo "$content" | grep -oE '"[^"]*"\s+"[^"]*"' | head -1 \
           | tr -d '"' | xargs | tr ' ' '.' || true)
    [[ -z "$name" ]] && name="${res}"
    emit "$(rel "$f")" "$l" "endpoint" "resource.${name}"
  done < <(grep -rn "^resource\s\+\"${res}\"" "$REPO_PATH" \
            --include="*.tf" 2>/dev/null || true)
done

# ── outputs (entry points for downstream consumers) ───────────────────────────
while IFS= read -r match; do
  f="${match%%:*}"; rest="${match#*:}"; l="${rest%%:*}"; content="${rest#*:}"
  [[ -z "$f" || -z "$l" ]] && continue
  name=$(echo "$content" | grep -oE '"[^"]*"' | head -1 | tr -d '"' || true)
  [[ -z "$name" ]] && name="(unnamed)"
  emit "$(rel "$f")" "$l" "entry_point" "output.${name}"
done < <(grep -rn "^output\s\+\"" "$REPO_PATH" \
          --include="*.tf" 2>/dev/null || true)

# ── test locations ────────────────────────────────────────────────────────────
# .tftest.hcl (native Terraform test framework)
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  emit "$(rel "$f")" 1 "test_location" "$(basename "$f")"
done < <(find "$REPO_PATH" -name "*.tftest.hcl" 2>/dev/null | head -20)

# Terratest (_test.go files under a test/ directory)
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  l=$(grep -n "func Test" "$f" 2>/dev/null | head -1 | cut -d: -f1 || echo "1")
  emit "$(rel "$f")" "${l:-1}" "test_location" "$(basename "${f%.go}")"
done < <(find "$REPO_PATH" -path "*/test*" -name "*_test.go" 2>/dev/null | head -20)

exit 0
