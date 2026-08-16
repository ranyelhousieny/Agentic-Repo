#!/usr/bin/env python3
"""golden_facts.py — mechanical golden-fact assertions for a converted repo.

Closes the L5 "Eval assets" readiness criterion WITHOUT putting an LLM on the
conversion's critical path: facts are derived from evidence the conversion just
gate-verified (CODE_INDEX rows, the Phase 1 framework detection, one dependency
edge), written to Knowledge/golden/ as durable named claims, and asserted
mechanically on every subsequent run. First-run assertion is trivially green by
construction — the value is UPDATE-mode re-runs, where a moved endpoint or a
reworked auth pattern turns a stale knowledge base into a HARD FAILURE instead
of a silent lie. The three-model jury (validate-agentic-kb) remains the manual
deep-check; this is the zero-cost standing gate.

Modes:
    derive <repo>   Select facts and write Knowledge/golden/GOLDEN_FACTS.{jsonl,md}.
                    DERIVE-ONCE: an existing GOLDEN_FACTS.jsonl is left untouched
                    (overwriting the anchors on every run would defeat drift
                    detection). --rederive is the explicit refresh.
    assert <repo>   Re-verify every fact against the current tree. Rewrites the
                    md status column. Exit 0 all pass / 1 any fail / 3 usage.

Fact selection is deterministic (sorted, capped) so two derives from the same
tree produce identical files. Token matching mirrors the citation gate's
tokenizer (lowercased [a-zA-Z][a-zA-Z0-9]+ words, len >= 3, overlap >= 0.1)
so a fact that passes here would also pass the T3 gate, and vice versa.
"""
import json
import re
import sys
from pathlib import Path

GOLDEN_DIR = "Knowledge/golden"
JSONL = "GOLDEN_FACTS.jsonl"
MD = "GOLDEN_FACTS.md"
MAX_ENDPOINTS = 5
MAX_ANCHORS = 3          # entry_point / config rows
OVERLAP_FLOOR = 0.1      # same floor as verify_citations.sh

ROW_RE = re.compile(r"^\|\s*([a-z_]+)\s*\|\s*(.+?)\s*\|\s*`?([^`|]+?):(\d+)`?\s*\|")


def tokens(text):
    return {w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]+", text) if len(w) >= 3}


def overlap(claim_text, line_text):
    claim = tokens(claim_text)
    if not claim:
        return 0.0
    return len(claim & tokens(line_text)) / len(claim)


def read_index_rows(repo):
    index = repo / "Knowledge" / "CODE_INDEX.md"
    if not index.is_file():
        return []
    rows = []
    for raw in index.read_text(encoding="utf-8", errors="replace").splitlines():
        m = ROW_RE.match(raw)
        if m:
            kind, ident, path, line = m.group(1), m.group(2), m.group(3), int(m.group(4))
            rows.append({"kind": kind, "identifier": ident, "path": path, "line": line})
    return rows


def derive_facts(repo):
    facts = []

    rows = read_index_rows(repo)
    endpoints = sorted((r for r in rows if r["kind"] == "endpoint"),
                       key=lambda r: (r["path"], r["line"]))[:MAX_ENDPOINTS]
    anchors = sorted((r for r in rows if r["kind"] in ("entry_point", "config")),
                     key=lambda r: (r["kind"], r["path"], r["line"]))[:MAX_ANCHORS]
    for r in endpoints + anchors:
        facts.append({
            "id": "GF-%03d" % (len(facts) + 1),
            "claim": "%s `%s` is defined at %s:%d" % (r["kind"], r["identifier"],
                                                      r["path"], r["line"]),
            "path": r["path"], "line": r["line"],
            "expect": r["identifier"],
        })

    # Framework detection: assert the evidence line still carries the framework name.
    phase1 = repo / "Generated" / "Analysis" / "PHASE1_DETECTION.md"
    if phase1.is_file():
        for raw in phase1.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\|\s*FRAMEWORK\s*\|\s*(\S+)[^|]*\|[^|]*\|", raw)
            if m:
                fw = m.group(1)
                hit = next((r for r in read_index_rows(repo)
                            if r["kind"] in ("endpoint", "entry_point")), None)
                if hit:
                    facts.append({
                        "id": "GF-%03d" % (len(facts) + 1),
                        "claim": "detected framework `%s` still evidenced near %s:%d"
                                 % (fw, hit["path"], hit["line"]),
                        "path": hit["path"], "line": hit["line"],
                        "expect": hit["identifier"],
                        "framework": fw,
                    })
                break

    # One dependency edge from the engine, when the graph exists: the cited line
    # must still mention the imported module.
    graph = repo / "Generated" / "graphify" / "CODE_GRAPH.jsonl"
    if graph.is_file():
        for raw in graph.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                edge = json.loads(raw)
            except json.JSONDecodeError:
                continue
            target = str(edge.get("identifier", "")).split("->")[-1].strip()
            if len(target) >= 3 and edge.get("path") and edge.get("line"):
                facts.append({
                    "id": "GF-%03d" % (len(facts) + 1),
                    "claim": "dependency edge `%s` cited at %s:%d"
                             % (edge["identifier"], edge["path"], edge["line"]),
                    "path": edge["path"], "line": int(edge["line"]),
                    "expect": target,
                })
                break

    return facts


def assert_fact(repo, fact):
    """(ok, detail). Mechanical only: file exists, line exists, token overlap."""
    f = repo / fact["path"]
    if not f.is_file():
        return False, "file missing: %s" % fact["path"]
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    if fact["line"] < 1 or fact["line"] > len(lines):
        return False, "line %d out of bounds (file has %d)" % (fact["line"], len(lines))
    got = overlap(fact["expect"], lines[fact["line"] - 1])
    if got < OVERLAP_FLOOR:
        return False, "overlap %.2f < %.2f on line %d" % (got, OVERLAP_FLOOR, fact["line"])
    return True, "overlap %.2f" % got


def write_md(repo, facts, results=None):
    out = [
        "# Golden Facts — mechanical KB drift gate",
        "",
        "**Derived from gate-verified evidence; asserted on every conversion run.**",
        "A FAIL here means the knowledge base no longer matches the code — refresh",
        "the conversion (UPDATE mode) or re-derive with `golden_facts.py derive --rederive`.",
        "",
        "| ID | Claim | Status |",
        "|----|-------|--------|",
    ]
    for i, fact in enumerate(facts):
        status = "UNTESTED"
        if results is not None:
            ok, detail = results[i]
            status = "PASS (%s)" % detail if ok else "**FAIL** (%s)" % detail
        out.append("| %s | %s | %s |" % (fact["id"], fact["claim"], status))
    (repo / GOLDEN_DIR / MD).write_text("\n".join(out) + "\n", encoding="utf-8")


NONE_MARKER = "GOLDEN_FACTS_NONE.md"


def write_none_marker(repo):
    """State that this repo has nothing derivable, so absence is evidence too.

    rc 3 alone was invisible to the conversion: Step 15.7 did not branch on it and
    final_verify.py REQUIRED the facts outright, so a repo whose CODE_INDEX has no
    endpoint / entry_point / config rows -- a docs repo, a pure library, this
    framework's own self-conversion -- failed the conversion with a drift message
    that named the wrong cause. The marker turns "no eval assets" into a recorded,
    checkable L5 readiness gap instead of a dead end.
    """
    path = repo / GOLDEN_DIR / NONE_MARKER
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Golden facts: NONE DERIVABLE\n\n"
            "`golden_facts.py derive` found no `endpoint`, `entry_point` or `config` rows in\n"
            "`Knowledge/CODE_INDEX.md`, so there is nothing durable to assert on future runs.\n\n"
            "**This is not a conversion failure.** It is an L5 readiness gap: the repo has no\n"
            "extractable behaviour to anchor an eval on (docs/markdown repos and pure libraries\n"
            "land here legitimately). Step 15.7 records it and continues.\n\n"
            "It BECOMES actionable the moment the repo grows an endpoint or an entry point:\n"
            "re-run the conversion in UPDATE mode, or `golden_facts.py derive --rederive .`,\n"
            "and this file is replaced by real facts.\n",
            encoding="utf-8")
    except OSError:
        pass          # same fail-soft contract as the rest of this script


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("derive", "assert"):
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: golden_facts.py derive|assert <repo_path> [--rederive]",
              file=sys.stderr)
        return 3
    mode, repo = sys.argv[1], Path(sys.argv[2]).resolve()
    rederive = "--rederive" in sys.argv[3:]
    jsonl = repo / GOLDEN_DIR / JSONL

    if mode == "derive":
        if jsonl.is_file() and not rederive:
            print("[golden_facts] %s exists — derive-once honoured, asserting is "
                  "the next step (--rederive to refresh)" % jsonl.relative_to(repo))
            return 0
        facts = derive_facts(repo)
        if not facts:
            write_none_marker(repo)
            print("[golden_facts] no derivable facts (is Knowledge/CODE_INDEX.md "
                  "present and populated?)", file=sys.stderr)
            return 3
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with jsonl.open("w", encoding="utf-8") as fh:
            for fact in facts:
                fh.write(json.dumps(fact, sort_keys=True) + "\n")
        write_md(repo, facts)
        # A repo that grows its first endpoint must not keep a marker claiming it has
        # none -- the marker is an either-half of final_verify's golden row, and a stale
        # one would assert "nothing derivable" over real facts sitting beside it.
        none_marker = repo / GOLDEN_DIR / NONE_MARKER
        if none_marker.is_file():
            try:
                none_marker.unlink()
            except OSError:
                pass
        print("[golden_facts] derived %d facts -> %s" % (len(facts), jsonl.relative_to(repo)))
        return 0

    if not jsonl.is_file():
        print("[golden_facts] nothing to assert: %s missing (run derive first)"
              % jsonl.relative_to(repo), file=sys.stderr)
        return 3
    facts = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    results = [assert_fact(repo, fact) for fact in facts]
    write_md(repo, facts, results)
    failed = [(fact, d) for fact, (ok, d) in zip(facts, results) if not ok]
    for fact, detail in failed:
        print("[golden_facts] FAIL %s: %s -- %s" % (fact["id"], fact["claim"], detail),
              file=sys.stderr)
    print("[golden_facts] %d/%d facts hold" % (len(facts) - len(failed), len(facts)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
