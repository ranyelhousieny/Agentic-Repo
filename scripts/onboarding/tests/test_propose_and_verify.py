"""propose_codeowners.py + final_verify.py — the CODEOWNERS draft and the
everything-created gate. Real git repos and real trees in tmp_path; no mocks.
"""
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True)


def git(repo, *args, env_id=None):
    base = ["git", "-C", str(repo)]
    if env_id:
        name, email = env_id
        base = ["git", "-C", str(repo),
                "-c", "user.name=%s" % name, "-c", "user.email=%s" % email]
    subprocess.run(base + list(args), capture_output=True, check=True)


def commit_as(repo, name, email, relpath, content):
    f = repo / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "work on %s" % relpath,
        env_id=(name, email))


# ── propose_codeowners ───────────────────────────────────────────────────────

def _seed_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    # Alice dominates overall; Bob owns services/; a bot spams commits.
    for i in range(5):
        commit_as(repo, "Alice", "alice@x.com", "lib/a%d.py" % i, "x = %d\n" % i)
    for i in range(25):
        commit_as(repo, "Bob", "bob@x.com", "services/s%d.py" % i, "y = %d\n" % i)
    for i in range(3):
        commit_as(repo, "renovate-bot", "renovate@bots.io", "lock%d.txt" % i, "%d" % i)
    return repo


def test_proposes_from_evidence_with_bots_filtered(tmp_path):
    repo = _seed_repo(tmp_path)
    r = run("propose_codeowners.py", repo)
    assert r.returncode == 0, r.stderr
    text = (repo / "CODEOWNERS.proposed").read_text()
    assert "DERIVED DRAFT" in text and "RENAME this file" in text
    root = next(l for l in text.splitlines() if l.startswith("* "))
    assert "bob@x.com" in root and "alice@x.com" in root
    assert "renovate" not in text                       # bot filtered
    # services/ has >= 20 commits and Bob is already the root #1 owner, so a
    # /services/ rule would repeat the root — it must NOT appear; and lib/ is
    # under the volume floor.
    assert "/services/" not in text and "/lib/" not in text


def test_governed_repo_is_left_alone(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / "CODEOWNERS").write_text("* @real-team\n")
    r = run("propose_codeowners.py", repo)
    assert r.returncode == 0
    assert "already governed" in r.stdout
    assert not (repo / "CODEOWNERS.proposed").exists()


def test_all_bot_history_is_a_loud_error_not_a_bot_codeowners(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    commit_as(repo, "dependabot", "dep@bots.io", "lock.txt", "1")
    r = run("propose_codeowners.py", repo)
    assert r.returncode == 3
    assert "no non-bot commits" in r.stderr
    assert not (repo / "CODEOWNERS.proposed").exists()


# ── final_verify ─────────────────────────────────────────────────────────────

def _converted_tree(tmp_path):
    """The conversion contract's full output, minimally populated."""
    repo = tmp_path / "c"
    for rel in ["CLAUDE.md", "AGENTS.md", "START_HERE.md", "BINDING.yml",
                "Knowledge/KNOWLEDGE_GRAPH.md", "Knowledge/DOCUMENT_INDEX.md",
                "Knowledge/CODE_INDEX.md", "Knowledge/SME_CONTACTS.md",
                "Knowledge/Source of Truth/PROJECT_VISION.md",
                "Knowledge/golden/GOLDEN_FACTS.jsonl",
                "Knowledge/golden/GOLDEN_FACTS.md",
                "Generated/PROGRESS_TRACKER.md",
                "Generated/Analysis/PHASE1_DETECTION.md",
                "Generated/VALIDATION_SUMMARY.md",
                "Generated/scripts/run_verify_citations.sh",
                ".claude/agents/developer.md", ".claude/agents/researcher.md",
                ".claude/agents/code-reviewer.md",
                ".claude/skills/c-agent/SKILL.md", ".claude/commands/c-ai.md",
                "prompts/templates/AI Agents/C_AI_AGENT.md",
                "CODEOWNERS.proposed",
                "Generated/graphify/CODE_GRAPH.jsonl"]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("content referencing CODE_INDEX.md\n")
    return repo


def test_complete_tree_passes(tmp_path):
    repo = _converted_tree(tmp_path)
    r = run("final_verify.py", repo)
    assert r.returncode == 0, r.stderr
    assert "checks pass" in r.stdout


def test_empty_file_fails_not_just_missing(tmp_path):
    """Existence-only checks cannot tell a created file from a failed one."""
    repo = _converted_tree(tmp_path)
    (repo / "CLAUDE.md").write_text("")
    r = run("final_verify.py", repo)
    assert r.returncode == 1
    assert "CLAUDE.md" in r.stderr and "missing or empty" in r.stderr


def test_unregistered_index_fails(tmp_path):
    repo = _converted_tree(tmp_path)
    (repo / "Knowledge" / "DOCUMENT_INDEX.md").write_text("no mention here\n")
    r = run("final_verify.py", repo)
    assert r.returncode == 1
    assert "DOCUMENT_INDEX" in r.stderr


def test_placeholder_leak_fails(tmp_path):
    repo = _converted_tree(tmp_path)
    (repo / "START_HERE.md").write_text(
        "Welcome to $REPO_NAME_LOWER, converted $TODAY. See CODE_INDEX.md.\n")
    r = run("final_verify.py", repo)
    assert r.returncode == 1
    assert "START_HERE.md" in r.stderr and "placeholder" in r.stderr


def test_loud_skip_satisfies_the_graph_alternative(tmp_path):
    """No engine output is acceptable ONLY with the loud-skip artifact."""
    repo = _converted_tree(tmp_path)
    (repo / "Generated" / "graphify" / "CODE_GRAPH.jsonl").unlink()
    r = run("final_verify.py", repo)
    assert r.returncode == 1                      # neither half -> fail
    (repo / "Generated" / "Analysis" / "GRAPHIFY_BOOTSTRAP.err").write_text(
        "rc=3: no python >= 3.10 on PATH\n")
    r = run("final_verify.py", repo)
    assert r.returncode == 0                      # loud skip -> contract met
