#!/usr/bin/env python3
"""
merge_sme_contacts.py — Merge auto-generated SME rows with human-edited content.

Usage:
    python3 scripts/onboarding/merge_sme_contacts.py \\
        --repo-path <REPO_PATH>       \\
        [--months 12]                 \\
        [--output <path>]             \\
        [--dry-run]

Reads:
  - git history via extract_git_ownership.sh (JSON-lines stdin or invoked as subprocess)
  - existing <REPO_PATH>/Knowledge/SME_CONTACTS.md (if present)

Writes:
  - <REPO_PATH>/Knowledge/SME_CONTACTS.md (merged result, unless --dry-run)
  - If --dry-run: prints the proposed diff to stdout; writes nothing.

Merge strategy (structural markers):
  The auto-generated block is delimited by:
      <!-- BEGIN AUTO -->
      ...rows...
      <!-- END AUTO -->
  Everything OUTSIDE those markers is hand-authored content and is preserved verbatim.
  On first run (no existing file) the whole file is created.
  On re-run the auto block is atomically replaced; hand-edited rows survive.

Schema (v2 upgrade):
  Each auto-generated row uses the v2 schema:
    Area | Original Architect (commits) | Current Maintainer (last commit) |
    CODEOWNERS | catalog-info owner | Agreement | Derivation Date

Exit 0 always — errors are reported to stderr, partial success is acceptable.

Requires: python3 3.9+, bash 3.2+ (for the subsidiary extract_git_ownership.sh script)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path


# ── markers ──────────────────────────────────────────────────────────────────
BEGIN_AUTO = "<!-- BEGIN AUTO -->"
END_AUTO   = "<!-- END AUTO -->"

SCRIPTS_DIR = Path(__file__).resolve().parent


def run_git_ownership(repo_path: Path, months: int) -> list[dict]:
    """Invoke extract_git_ownership.sh and parse its JSON-lines output."""
    script = SCRIPTS_DIR / "extract_git_ownership.sh"
    if not script.exists():
        print(f"[merge_sme_contacts] WARNING: {script} not found; skipping git extraction",
              file=sys.stderr)
        return []
    try:
        result = subprocess.run(
            ["bash", str(script), str(repo_path), "--months", str(months)],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"[merge_sme_contacts] WARNING: git extraction failed: {exc}", file=sys.stderr)
        return []

    rows = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"[merge_sme_contacts] WARNING: bad JSON line: {line!r} — {e}",
                  file=sys.stderr)
    return rows


def build_auto_block(rows: list[dict], months: int, today: str) -> str:
    """Render the auto-generated table section (ownership schema)."""
    lines = [
        BEGIN_AUTO,
        f"<!-- Auto-generated {today} — {months}-month git window. DO NOT EDIT; hand rows go OUTSIDE this block. -->",
        "",
        "## Auto-Derived Ownership (git history — ownership schema v2)",
        "",
        (f"*Window: {months} months ending {today}. "
         "Re-running `/project:convert-repo-to-agentic` refreshes this block without touching rows outside it.*"),
        "",
        "| Area | Original Architect (commits) | Current Maintainer (last commit) "
        "| CODEOWNERS | catalog-info owner | Agreement | Derivation Date |",
        "|------|------------------------------|----------------------------------"
        "|------------|-------------------|-----------|-----------------|",
    ]
    for row in rows:
        area = row.get("area", "(unknown)")

        # ownership fields (v2 schema)
        original_architect = row.get("original_architect") or "—"
        current_maintainer = row.get("current_maintainer") or "—"
        codeowners_entry   = row.get("codeowners_entry") or "—"
        catalog_info_owner = row.get("catalog_info_owner") or "—"
        agreement          = row.get("agreement") or "SINGLE_SOURCE"
        derivation_date    = row.get("derivation_date") or today

        lines.append(
            f"| `{area}` | {original_architect} | {current_maintainer} "
            f"| {codeowners_entry} | {catalog_info_owner} | {agreement} | {derivation_date} |"
        )
    if not rows:
        lines.append("| (no commits found in window) | — | — | — | — | SINGLE_SOURCE | — |")
    lines += ["", END_AUTO]
    return "\n".join(lines)


def merge(existing: str, auto_block: str) -> str:
    """Replace the auto block in existing content, or append it if absent."""
    if BEGIN_AUTO in existing and END_AUTO in existing:
        before = existing[:existing.index(BEGIN_AUTO)]
        after  = existing[existing.index(END_AUTO) + len(END_AUTO):]
        return before + auto_block + after
    # No markers yet — append auto block at the end
    return existing.rstrip("\n") + "\n\n" + auto_block + "\n"


def new_file_skeleton(repo_path: Path, auto_block: str, today: str) -> str:
    """Generate a brand-new SME_CONTACTS.md."""
    repo_name = repo_path.name
    return f"""# {repo_name} — SME Contacts and Ownership

**Last Updated:** {today}

> **How to use this file:**
> - The `BEGIN AUTO ... END AUTO` block is machine-generated from git history.
>   Re-running `/project:convert-repo-to-agentic` refreshes it automatically.
> - Add your own rows, escalation contacts, or notes **outside** the AUTO block.
>   They will never be overwritten.

---

## Hand-Authored Contacts

<!-- Add team contacts, on-call paths, and domain owners here.
     This section is preserved verbatim on every re-run. -->

| Name | Role | Area | Contact |
|------|------|------|---------|
|      |      |      |         |

---

{auto_block}

---

*Generated by Agentic-Repos framework — `scripts/onboarding/merge_sme_contacts.py`*
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Merge auto SME rows into SME_CONTACTS.md")
    p.add_argument("--repo-path", required=True, help="Absolute or relative path to target repo")
    p.add_argument("--months", type=int, default=12,
                   help="Git history look-back window in months (default: 12)")
    p.add_argument("--output", default=None,
                   help="Output path (default: <REPO_PATH>/Knowledge/SME_CONTACTS.md)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print proposed content to stdout; do not write to disk")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    repo_path = Path(args.repo_path).resolve()
    today = date.today().isoformat()
    output_path = Path(args.output) if args.output else repo_path / "Knowledge" / "SME_CONTACTS.md"

    # 1. Extract git ownership
    rows = run_git_ownership(repo_path, args.months)

    # 2. Build the auto block (ownership schema)
    auto_block = build_auto_block(rows, args.months, today)

    # 3. Merge with existing content (or generate skeleton)
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        merged = merge(existing, auto_block)
        action = "updated"
    else:
        merged = new_file_skeleton(repo_path, auto_block, today)
        action = "created"

    # 4. Output
    if args.dry_run:
        print(f"=== DRY RUN: proposed SME_CONTACTS.md ({action}) ===")
        print(merged)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(merged, encoding="utf-8")
    print(f"[merge_sme_contacts] {action}: {output_path}", file=sys.stderr)
    print(json.dumps({"status": action, "path": str(output_path), "rows": len(rows)}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"[merge_sme_contacts] FATAL: {exc}", file=sys.stderr)
        sys.exit(0)   # exit 0 so callers never abort on SME extraction failure
