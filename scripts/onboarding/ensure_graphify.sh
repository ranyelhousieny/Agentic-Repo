#!/usr/bin/env bash
# ensure_graphify.sh — resolve the Graphify engine, INSTALLING it if necessary.
#
# The dependency graph is what separates a rich agent (symbol-level CODE_INDEX,
# CODE_GRAPH.jsonl impact analysis, quarantined-uncertainty sidecar) from a
# surface-level one, so Phase 1.5 treats the engine as expected-present: this
# script tries every reasonable path to an engine before conceding, and a skip
# is legitimate ONLY when installation is provably impossible on this machine.
#
# Resolution ladder (first success wins):
#   1. GRAPHIFY_PYTHON override        — operator says exactly which interpreter
#   2. Existing engine venv            — reuse; a broken venv is rebuilt, not trusted
#   3. Bootstrap                       — newest compatible python3.x creates the venv
#                                        and pip-installs the pinned engine
#
# Exit codes (the caller keys behavior off these — keep them stable):
#   0  engine ready; the venv's python path is on STDOUT (nothing else ever is)
#   2  disabled by the operator (GRAPHIFY_ADAPTER=0/false/no/off) — respected, quiet
#   3  impossible on this machine; the reason is on STDERR (no python >= 3.10,
#      venv creation failed, pip install failed e.g. offline, corrupt install)
#
# Env:
#   GRAPHIFY_PIN              engine pin        (default: graphifyy==0.9.43)
#   GRAPHIFY_VENV_DIR         venv location     (default: $HOME/.venvs/graphify)
#   GRAPHIFY_PYTHON           explicit interpreter override (must already import graphifyy)
#   GRAPHIFY_ADAPTER          kill switch, same semantics as the Phase 1.5 guard
#
# bash 3.2 floor applies (no ${VAR,,}); verified constructs only.
set -euo pipefail

PIN="${GRAPHIFY_PIN:-graphifyy==0.9.43}"
VENV_DIR="${GRAPHIFY_VENV_DIR:-$HOME/.venvs/graphify}"

# Operator kill switch — mirror the Phase 1.5 guard exactly (`${VAR-1}` not `${VAR:-1}`,
# lowercase + strip whitespace) so the two layers can never disagree.
FLAG="$(printf '%s' "${GRAPHIFY_ADAPTER-1}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
case "$FLAG" in
  1|true|yes|on) : ;;
  *) echo "disabled by operator (GRAPHIFY_ADAPTER=${GRAPHIFY_ADAPTER-})" >&2; exit 2 ;;
esac

# Dist name and module name DIFFER: pip installs `graphifyy` (the pin), python
# imports `graphify` (measured on the real 0.9.43 wheel — `import graphifyy` fails
# on a perfectly healthy install). Probe both so a future rename keeps working.
engine_ok() { "$1" -c "import graphify" >/dev/null 2>&1 || "$1" -c "import graphifyy" >/dev/null 2>&1; }

# 1. Explicit override: trust it or fail loudly — never silently guess past an
#    operator's stated intent.
if [ -n "${GRAPHIFY_PYTHON:-}" ]; then
  if engine_ok "$GRAPHIFY_PYTHON"; then
    echo "$GRAPHIFY_PYTHON"
    exit 0
  fi
  echo "GRAPHIFY_PYTHON=$GRAPHIFY_PYTHON is set but cannot import the engine (graphify/graphifyy)" >&2
  exit 3
fi

# 2. Existing venv: reuse when healthy. A dir that exists but cannot import the
#    engine is BROKEN (half-finished install, wrong python after an OS upgrade) —
#    fall through and rebuild it from scratch rather than trusting it.
if [ -x "$VENV_DIR/bin/python" ] && engine_ok "$VENV_DIR/bin/python"; then
  echo "$VENV_DIR/bin/python"
  exit 0
fi

# 3. Bootstrap. Newest interpreter first: the engine needs python >= 3.10 and a
#    stock macOS `python3` is 3.9, so probing only `python3` would concede on
#    machines that actually carry a perfectly good 3.12/3.13.
BASE_PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 \
     && "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    BASE_PY="$(command -v "$cand")"
    break
  fi
done
if [ -z "$BASE_PY" ]; then
  echo "no python >= 3.10 on PATH — cannot install ${PIN} (install python 3.10+ and re-run)" >&2
  exit 3
fi

[ -e "$VENV_DIR" ] && rm -rf "$VENV_DIR"
mkdir -p "$(dirname "$VENV_DIR")"
if ! "$BASE_PY" -m venv "$VENV_DIR" 2>/dev/null; then
  echo "venv creation failed with $BASE_PY at $VENV_DIR" >&2
  exit 3
fi

# pip's own network timeout + bounded retries: a hung index fetch must degrade to
# exit 3 with a reason, not stall the whole conversion.
INSTALL_ERR="$VENV_DIR/.install_err"
if ! "$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check \
       --timeout 60 --retries 2 "$PIN" 2> "$INSTALL_ERR"; then
  echo "pip install '$PIN' failed (offline? blocked index?): $(tail -3 "$INSTALL_ERR" 2>/dev/null | tr '\n' ' ')" >&2
  exit 3
fi

if ! engine_ok "$VENV_DIR/bin/python"; then
  echo "pip reported success but the engine module does not import — corrupt install at $VENV_DIR" >&2
  exit 3
fi

echo "$VENV_DIR/bin/python"
exit 0
